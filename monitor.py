import requests, time, re, random, keyring, logging, json, os
from tqdm import tqdm
from bs4 import BeautifulSoup
from urllib.parse import urljoin

logging.basicConfig(level=logging.INFO)
user_agent = {'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/94.0.4606.71 Safari/537.36 Edg/94.0.992.38'}


# initial config
with open('config.json', 'r') as cfg:
    tmp = json.load(cfg)

    if not tmp['webhook_url']:
        webhook = input("Please enter your webhook url: ")
        tmp['webhook_url'] = webhook
        with open('config.json', 'w') as update:
            json.dump(tmp, update)
        logging.info("Webhook successfully set")

    else:
        webhook = tmp['webhook_url']
        logging.info("Webhook retrieved")

isl = 'https://is.muni.cz/auth/'
exams_link = 'https://is.muni.cz/auth/student/prihl_na_zkousky'
block_link = 'https://is.muni.cz/auth/student/poznamkove_bloky_nahled'

min_sleep = int(input("Minimum sleep time (ex. 300): ")) # time in seconds, make sure to not get rate limited
max_sleep = int(input("Maximum sleep time (ex. 700): "))


def get_credentials():
    env_user = os.getenv('IS_MUNI_UCO')
    env_password = os.getenv('IS_MUNI_PASSWORD')

    if env_user and env_password:
        logging.info('Loaded IS credentials from environment variables.')
        return env_user, env_password

    logging.info('Environment variables not set, attempting to load credentials from keyring.')
    user = keyring.get_password('is-mon', 'uco')
    password = keyring.get_password('is-mon', 'password')

    if user and password:
        logging.info('Loaded IS credentials from keyring.')
        return user, password

    logging.warning('Credentials not found in env vars or keyring. Prompting for manual input.')
    user = input('Enter your IS MUNI UCO: ')
    password = input('Enter your IS MUNI password: ')
    return user, password



def login(session, user, password):
    logging.info("Logging in...")
    while True:
        try:
            init = session.get(isl, allow_redirects=True)
            login_post = session.post(init.url, data={"akce":"login", "credential_0":user, "credential_1":password, "uloz":"uloz"}, allow_redirects=True, timeout = 10)
            break
        except ConnectionError:
            logging.info("Connection error, trying again in 10 seconds")
            time.sleep(10)

    if login_post.url == isl:
        logging.info("Login successful")
    else:
        logging.error("Login failed, invalid credentials, reset your keyring")
        exit(1)

    return session




def get_notes(session):         # get the notebook page, return the most recent change
    init = session.get(block_link, timeout = 10)
    soup = BeautifulSoup(init.text,'html.parser')
    last_change = soup.find('a',{'id':'odkaz_na_posledni_akci'})
    return last_change, session



def monitor_notebook(session):

    while True:
        try:
            last_change, session = get_notes(session)   # initial fetch of the notebook
            break
        except Exception as e:
            sl_t = random.randint(min_sleep, max_sleep)
            logging.error(f'Exception {e} occurred while setting up. Sleeping for {sl_t} seconds.')
            for i in tqdm(range(100)):
                time.sleep(sl_t/100)
    logging.info("Started monitoring...")

    while True:

        try:
            new_change, session = get_notes(session)    # new fetch of the notebook

            if new_change.text != last_change.text:     # comparison between the two

                change_req = session.get(block_link + new_change['href'])
                soup = BeautifulSoup(change_req.text,'html.parser')

                # get information about the change
                row = soup.find('div',{'id':str(re.sub('#','', new_change['href']))})
                title = row.find('div',{'class':'column small-12 medium-3 tucne ipb-nazev'}).text
                desc = row.find('pre').text
                title = title[8:len(title)-7]
                new_split = new_change.text.split(',')

                logging.info(f"Detected a change... Title: {title} Description: {desc}")
                embed = {'embeds':[{'title': new_split[3],'color':7988011,'fields':[{'name':f'**{title}**','value':desc}],'footer':{'text': f'{new_split[0][16:]}, {new_split[1]}'}}]}
                requests.post(webhook,json = embed)     # post information about the change to the discord webhook
                logging.info("Successfully posted to webhook")
                last_change = new_change                # update the change


            sl_t = random.randint(min_sleep, max_sleep) # random sleep interval
            logging.info(f'Sleeping for {sl_t} seconds.')
            for i in tqdm(range(100)):                  # progress bar using tqdm
                time.sleep(sl_t/100)

        except Exception as e:
            sl_t = random.randint(min_sleep, max_sleep)
            logging.error(f'Exception {e} occurred. Sleeping for {sl_t} seconds.')
            for i in tqdm(range(100)):
                time.sleep(sl_t/100)



def submit_swap_confirmation(session, soup, exam_date):
    form = soup.find('form')
    if not form or not form.find('input', {'name': 'prehlasit'}):
        return None

    payload = {}
    submit_fields = []
    for field in form.find_all('input'):
        name = field.get('name')
        if not name:
            continue
        value = field.get('value', '')
        if field.get('type', '').lower() == 'submit':
            submit_fields.append((name, value))
        else:
            payload[name] = value

    if not submit_fields:
        # fallback if submit button is not explicitly marked, IS expects "button=Ano"
        submit_fields.append(('button', 'Ano'))

    for name, value in submit_fields:
        payload[name] = value

    action = form.get('action')
    if not action:
        return None

    action_url = urljoin(exams_link, action)
    logging.info(f'Confirmation required for {exam_date}. Attempting to submit swap form...')
    try:
        response = session.post(action_url, data=payload, timeout=10)
    except Exception as exc:
        logging.error(f'Failed to submit swap form: {exc}')
        return None
    return response


def exam_signup(session):
    
    # fetch available subjects
    logging.info('Fetching subject list...')
    while True:
        try:
            exam_master = session.get(exams_link)
            break
        except Exception as e:
            logging.error(f'Exception {e} occurred while setting up. Sleeping for 10 seconds.')
            time.sleep(10)
    soup = BeautifulSoup(exam_master.text, 'html.parser')
    sub_dict = {}

    print("\nAvailable subjects")
    print("------------------")
    i = 0
    for subject in soup.find('main',{'id':'app_content'}).find('ul').find_all('li'):

        # retrieve info about the subject
        sub_code = subject.text.split(' ')[0]
        sub_href = f"{exams_link}{subject.find('a')['href'][18:]}"
        sub_dict[i] = sub_href
        print(f"{i}: {sub_code}")
        i += 1

    chosen_sub = int(input('Please choose a subject code from the options above (number): '))
    
    # after the subject is chosen, check for available exam dates
    logging.info('Fetching exam dates...')
    exam_entries_req = session.get(sub_dict[chosen_sub], timeout = 10)
    soup = BeautifulSoup(exam_entries_req.text,'html.parser')

    # edge case where the subject has no exams or is already completed
    notif = soup.find('div',{'class':'zdurazneni info'})
    if notif:
        notif_text = notif.find('p').text
        if notif_text.endswith('není v budoucnosti vypsán již žádný termín, nebo máte předmět již úspěšně ukončen.'):
            logging.info('The subject has no exam dates or you have already completed it.')
            exit(0)             
    

    exam_entries = {}
    count = 0
    print("\nAvailable dates")
    print("------------------")

    # go through all available exams
    for entry in soup.find_all('tr',{'valign':'top'}):
        # retrieve information about the exam
        exam_status = entry.find_all('td')[0].text
        details_cell = entry.find_all('td')[2]
        exam_date = details_cell.find('b').text
        capacity_status = details_cell.text

        exam_href = None
        for anchor in details_cell.find_all('a', href=True):
            href = anchor['href']
            if 'prihl_na_zkousky' in href and 'prihlasit' in href:
                exam_href = urljoin(exams_link, href)
                break

        max_cap = re.search(r'max. (\d+)', capacity_status)
        if max_cap:
            max_cap = max_cap[1]
        else:
            max_cap = ''
        current_cap = re.search(r'přihlášeno (\d+)', capacity_status)[1]
        exam_entries[count] = {
            'date': exam_date,
            'status': exam_status,
            'link': exam_href,
            'max_capacity': max_cap,
            'current_signedup': current_cap
        }
        suffix = '' if exam_href else ' [already enrolled – swap only]'
        print(f'{count}: {exam_date}, CAPACITY: {current_cap}/{max_cap}{suffix}')
        count += 1

    if not exam_entries:
        logging.info('No exam dates are currently available for this subject.')
        exit(0)

    def parse_exam_choices(raw_choices, max_idx):
        tokens = [token.strip() for token in raw_choices.split(',')]
        parsed = []
        for token in tokens:
            if not token:
                continue
            if not token.isdigit():
                raise ValueError('Choices must be numeric indices separated by commas.')
            idx = int(token)
            if idx < 0 or idx > max_idx:
                raise ValueError(f'Choice {idx} is out of range. Valid range is 0-{max_idx}.')
            parsed.append(idx)
        if not parsed:
            raise ValueError('At least one exam date must be selected.')
        return sorted(set(parsed))

    max_idx = count - 1
    while True:
        raw_choice = input(f'Choose one or more dates (comma-separated) [0-{max_idx}]: ')
        try:
            chosen_dates = parse_exam_choices(raw_choice, max_idx)
            break
        except ValueError as err:
            logging.error(err)

    selected_exams = {idx: exam_entries[idx] for idx in chosen_dates}

    no_link = [idx for idx, exam in selected_exams.items() if not exam['link']]
    if no_link:
        logging.error(f'Selected exam(s) {", ".join(str(idx) for idx in no_link)} cannot be auto-monitored because no signup link is available (you are likely already enrolled).')
        logging.error('Please remove these selections or manually unenroll before running the script.')
        exit(1)

    already_signed = [idx for idx, exam in selected_exams.items() if exam['link'] and 'burza' in exam['link']]
    if already_signed:
        logging.error(f'You are already signed up for date(s): {", ".join(str(idx) for idx in already_signed)}. Remove them from your selection and try again.')
        exit(1)

    logging.info(f'Monitoring {len(selected_exams)} exam date(s) for open capacity...')

    while True:
        for idx, exam_data in selected_exams.items():
            exam_link = exam_data['link']

            try:
                signup_req = session.get(exam_link, timeout = 10)
            except Exception as e:
                logging.error(f'Exception {e} occurred while checking {exam_data["date"]}. Moving to the next date.')
                continue

            soup = BeautifulSoup(signup_req.text, 'html.parser')

            # the user has successfully signed up
            success_status = soup.find('div', {'class': 'zdurazneni potvrzeni'})
            if success_status:
                logging.info(f'Successfully signed up for the exam on {exam_data["date"]}.')
                embed = {'embeds':[{'title': "Exam signup",'color':7988011,'fields':[{'name':f'**{exam_data["date"]}**','value':"Signed up!"}]}]}
                requests.post(webhook, json = embed)
                return

            # the user doesn't meet the requirements to sign up
            notification_status = soup.find('div', {'class': 'zdurazneni upozorneni'})
            if notification_status:
                swap_response = submit_swap_confirmation(session, soup, exam_data["date"])
                if swap_response:
                    swap_soup = BeautifulSoup(swap_response.text, 'html.parser')
                    success_status = swap_soup.find('div', {'class': 'zdurazneni potvrzeni'})
                    if success_status:
                        logging.info(f'Successfully swapped to the exam on {exam_data["date"]}.')
                        embed = {'embeds':[{'title': "Exam signup",'color':7988011,'fields':[{'name':f'**{exam_data["date"]}**','value':"Signed up!"}]}]}
                        requests.post(webhook, json = embed)
                        return

                    error_status = swap_soup.find('div', {'class': 'zdurazneni chyba'})
                    if error_status and error_status.find('h3'):
                        logging.error(f'Swap failed for {exam_data["date"]}: {error_status.find("h3").text}')
                    else:
                        logging.error('Swap confirmation submitted but no success status was returned. Please verify manually.')
                    return

                logging.error('Swap confirmation required but could not be processed automatically. Please handle manually.')
                return

            # the exam is full or another error occurred
            error_status = soup.find('div',{'class':'zdurazneni chyba'})
            if error_status:
                error_text = error_status.find('h3').text
                if error_text == 'Na tento termín se nelze přihlásit. Kapacitní limit zkušebního termínu je již zaplněn.':

                    logging.info(f'Exam on {exam_data["date"]} is still full.')
                    continue
                logging.error(f'Unexpected error for {exam_data["date"]}: {error_text}')

        sl_t = random.randint(min_sleep, max_sleep)
        logging.info(f'No availability detected. Sleeping for {sl_t} seconds before retrying all selected dates.')
        for i in tqdm(range(100)):
            time.sleep(sl_t/100)

print('1: Notebook monitoring')
print('2: Exam signup')
while True:
    mode = int(input('Please enter your desired mode: '))
    if mode < 1 or mode > 2:
        logging.error('Invalid choice, try again.')
    else:
        break

session = requests.Session()
session.headers.update(user_agent)
user, password = get_credentials()
session = login(session, user, password)

if mode == 1:
    monitor_notebook(session)
elif mode == 2:
    exam_signup(session)

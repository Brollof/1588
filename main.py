import os
import json
import time
import base64
import logging
import argparse
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from email.mime.text import MIMEText
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials


def get_fullpath(filename):
    script_dir = os.path.dirname(os.path.realpath(__file__))
    return os.path.join(script_dir, filename)


LOG_FILEPATH = get_fullpath("bot.log")
CREDENTIALS_FILEPATH = get_fullpath("credentials.json")
TOKEN_FILEPATH = get_fullpath("token.json")
SETTINGS_FILEPATH = get_fullpath("settings.json")
URL = "https://wrzeszcz.1588.pl/takeaway/online-menu/"
DEFAULT_CHECK_PERIOD_H = 1

OPEN_HOURS = {
    0: (11, 20), # Monday
    1: (11, 20),
    2: (11, 20),
    3: (11, 20),
    4: (11, 20),
    5: (12, 21),
    6: (12, 21)  # Sunday
}

sleep_hours = lambda h: time.sleep(h * 3600)


def send_email(to: str, message: str):
    SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

    creds = None
    if os.path.exists(TOKEN_FILEPATH):
        creds = Credentials.from_authorized_user_file(TOKEN_FILEPATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILEPATH, SCOPES)
            creds = flow.run_local_server(port=0)

        # Save the credentials for the next run
        with open(TOKEN_FILEPATH, "w") as token:
            token.write(creds.to_json())

    service = build("gmail", "v1", credentials=creds)
    message = MIMEText(message)
    message["to"] = to
    message["subject"] = "Pierogarnia 1588"
    create_message = {"raw": base64.urlsafe_b64encode(message.as_bytes()).decode()}

    try:
        message = (service.users().messages().send(userId="me", body=create_message).execute())
        logging.info(f"Sent message to '{message}'. Message Id: {message["id"]}")
    except requests.HTTPError as error:
        logging.error(f"An error occurred: {error}")


def prepare_message(report_data: dict[str, str]):
    msg = ""
    for menu_item_name, availability in report_data.items():
        msg += f"{menu_item_name}: {availability}\n"
    return msg


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--period", type=int, default=DEFAULT_CHECK_PERIOD_H, help="Check period (hours)")
    parser.add_argument("-f", "--force", action="store_true", default=False, help="Send report even when everything is sold out")
    args = parser.parse_args()

    period_h = args.period
    force_send = args.force

    log_handlers = [logging.FileHandler(LOG_FILEPATH)]
    log_handlers.append(logging.StreamHandler())

    logging.basicConfig(
        level=logging.DEBUG,
        format='[%(asctime)s] %(levelname)s: %(message)s',
        datefmt='%d.%m.%Y %H:%M:%S',
        handlers=log_handlers)

    logging.info("Pierogi bot started")
    logging.info(f"Checking every {period_h} hour(s)")

    try:
        with open(SETTINGS_FILEPATH, encoding="utf-8") as file:
            settings = json.loads(file.read())
            checklist = settings["checklist"]
            recipient = settings["recipient"]
            if len(checklist) == 0:
                raise Exception("Checklist cannot be empty!")
    except Exception as e:
        logging.critical(e)
        return

    while True:
        now = datetime.now()
        open_today, close_today = OPEN_HOURS[now.weekday()]
        if (open_today <= now.hour < close_today - 1) or force_send:
            try:
                response = requests.get(URL)
            except Exception as e:
                logging.critical(f"Bad URL: '{URL}'")
                logging.critical(e)
                return

            soup = BeautifulSoup(response.text, 'html.parser')

            raw_data = soup.find(id="__NEXT_DATA__")
            data = json.loads(raw_data.contents[0])
            menu_items = data["props"]["app"]["menu"]

            report_data = {}

            send_mail = False
            for item in menu_items:
                found = False
                for check in checklist:
                    item_name = item["name"]
                    if check in item_name.lower():
                        logging.debug(f"Item '{item_name}': {item["attributes"]}")
                        if 'SOLD_OUT' not in item["attributes"]:
                            send_mail = True
                            logging.info("Item found, email will be send")
                            report_data[item_name] = "Available"
                        else:
                            report_data[item_name] = "Sold out"
                    found = True
                if not found:
                    report_data[check] = "Not found!"

            if send_mail or force_send:
                msg = prepare_message(report_data)
                logging.info(f"Sending message:\n{msg}")
                # send_email(recipient, msg)
            else:
                logging.info("Not sending email - everything is sold out")

            open_today, close_today = OPEN_HOURS[datetime.now().weekday()]
            now = datetime.now()
        else:
            logging.info(f"It's closed, there's no point in checking the menu")

        logging.info(f"Going to sleep for {period_h} hour(s)...")
        sleep_hours(period_h)


if __name__ == '__main__':
    main()

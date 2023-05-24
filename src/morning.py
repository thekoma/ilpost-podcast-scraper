#!/usr/bin/env python3
"""This stupid webapp catches the latest morning post from ilpost.it ."""
import orjson, json
import os
import pickle
import time
import redis
import requests
import logging
import re
from dotenv import load_dotenv
from typing import Union
from fastapi import FastAPI, status, Response, Request
from fastapi.responses import PlainTextResponse, ORJSONResponse, HTMLResponse
from selenium import webdriver
import selenium.common.exceptions
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.remote.remote_connection import LOGGER as SeleniumLogger
from fastapi.security import OAuth2PasswordBearer

load_dotenv()
time.tzset()

# setup loggings
# logging.config.fileConfig('logging.conf', disable_existing_loggings=False)

# get root logging
SeleniumLogger.setLevel(logging.WARNING)
LOGLEVEL = os.getenv("LOGLEVEL", "INFO")
logging.basicConfig(format='%(levelname)s: %(message)s', level=LOGLEVEL)
USERAGENT = os.getenv("USERAGENT", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36")
# Values from envirionment
USERNAME = os.getenv("LOGIN_USER")
PASSWORD = os.getenv("LOGIN_PASSWORD")
SELENIUM_URL = os.getenv("SELENIUM_URL", "http://selenium:4444")
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
CACHE_TIME = int(os.getenv("CACHE_TIME", "43200")) # 43200 is 12 hours
CHECK_SITE = os.getenv("CHECK_SITE", "https://www.google.com")
# Used Variables
SELENIUM_HUB = SELENIUM_URL + "/wd/hub"
LOGIN_PAGE = "https://www.ilpost.it/wp-login.php?redirect_to=https://www.ilpost.it"
MORNING_PAGE = "https://www.ilpost.it/podcasts/morning/"
USERNAME_XPATH = "//input[@id='user_login']"
PASSWORD_XPATH = "//input[@id='user_pass']"
CHECKBOX_XPATH = "//input[@id='rememberme']"
LOGIN_XPATH = '//input[@id="wp-submit"]'
PLAYER_XPATH = '//audio[@id="ilpostPlayerAudio"]'
SCRAPE_RETRIES = int(os.getenv("SCRAPE_RETRIES", "10"))


# Initialize the Chrome Browser Options.
opts = Options()

# Let's set a credible UserAgent
opts.add_argument("user-agent="+USERAGENT)
# We prefer to use /tmp as SHM is a finite resource.
opts.add_argument('disable-dev-shm-usage')

# Init Objects
r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, socket_timeout=1)
app = FastAPI()

def get_cookies_redis():
    """Return false if redis has no cookies.
    Otherwise return cookies."""
    logging.debug("👾 Start get_cookies_redis")
    pickled_cookies = r.get("cookies")
    try:
        cookies = pickle.loads(pickled_cookies)
    except (TypeError):
        cookies = create_cookies()
    now = time.time()
    logging.info(f"Found {len(cookies)} cookies in redis!")
    for cookie in cookies:
        if cookie.get("expiry"):
            if now > cookie.get("expiry"):
                if len(cookie.get("value")) > 10:
                    logging.info(
                        f"[🔴] {cookie.get('name')} - \
                        Expired: {time.ctime(cookie.get('expiry'))}"
                    )
                    cookies = None
                else:
                    logging.info(
                        f"[🟠] {cookie.get('name')} - \
                        Ignored: {time.ctime(cookie.get('expiry'))}"
                    )
            else:
                logging.info(f"[🟢] {cookie.get('name')}")
        else:
            logging.info(f"[🟢] {cookie.get('name')} (session)")

    logging.debug("👾 End get_cookies_redis")
    return cookies

def create_cookies():
    """Create new cookies on wordpress!"""
    logging.debug("👾 Start create_cookies")
    logging.debug("👾 Open Driver!")


    driver = webdriver.Remote(command_executor=SELENIUM_HUB, options=opts)
    logging.info("Creating New Cookies!")
    with driver:
        driver.get(LOGIN_PAGE)
        logging.debug("Fill Credentials")
        elem = driver.find_element(By.XPATH, USERNAME_XPATH)
        elem.send_keys(USERNAME)
        elem = driver.find_element(By.XPATH, PASSWORD_XPATH)
        elem.send_keys(PASSWORD)
        elem = driver.find_element(By.XPATH, CHECKBOX_XPATH)
        elem.click()
        try:
            logging.debug("Login")
            elem = driver.find_element(By.XPATH, LOGIN_XPATH)
            elem.click()
        except NoSuchElementException as missing:
            logging.debug(missing.message)
        except TimeoutException as timeout:
            logging.debug(timeout.message)

        cookies = driver.get_cookies()
        while len(cookies) < 3:
            logging.debug(driver.get_cookies())
            cookies = driver.get_cookies()
            logging.debug("Numero di cookies: " + str(len(driver.get_cookies())))
        r.set("cookies", pickle.dumps(cookies))
        logging.debug("👾 Close Driver!")
        logging.debug("👾 SLEEEEEEEEP!")
        driver.close()
        logging.debug("👾 End create_cookies")
        return cookies

def is_selenium_available():
    """Check if selenium is available"""
    logging.debug("Getting url " + SELENIUM_HUB + "/status")
    try:
        response = requests.get(SELENIUM_HUB + "/status")
        status = response.status_code
    except requests.exceptions.RequestException as e:  # This is the correct syntax
        status = 500
    logging.debug(status)
    if status != 200:
        accessible = False
        logging.error("Returned value different from 200 -> " + str(status))
    else:
        logging.info("Returned 200")
        accessible = True
    return accessible, status

def is_selenium_working():
    driver = webdriver.Remote(command_executor=SELENIUM_HUB, options=opts)

    # driver = webdriver.Remote(
    #     command_executor=SELENIUM_HUB, options=webdriver.ChromeOptions()
    # )
    with driver:
        logging.debug("Navigate to " + CHECK_SITE)
        try: driver.get(CHECK_SITE)
        except selenium.common.exceptions.WebDriverException as e:
            logging.debug("######### ERRORE NELL'APRIRE IL SITO")
            logging.debug(e.msg)
            raise e
    driver.close()
    return "200"

def is_redis_available():
    """Check if redis is ready!"""
    try:
        r.memory_stats()
    except (redis.exceptions.ConnectionError, redis.exceptions.BusyLoadingError, redis.exceptions.TimeoutError):
        return False
    return True

def get_cookies():
    """Get cookies or try generatin new ones"""
    cookies = get_cookies_redis()
    if not cookies:
        logging.info("Validazione Cookie fallita, avvio la rigenerazione")
        cookies = create_cookies()
    return cookies

def send(driver, cmd, params={}):
    resource = "/session/%s/chromium/send_command_and_get_result" % driver.session_id
    url = driver.command_executor._url + resource
    body = json.dumps({'cmd': cmd, 'params': params})
    response = driver.command_executor._request('POST', url, body)
    return response.get('value')

def load_cookies(driver):
    cookies = get_cookies()
    logging.debug("🍪 deleting all cookies")
    driver.delete_all_cookies()
    send(driver, 'Network.enable', params={})
    while len(driver.get_cookies()) < len(cookies):
        logging.debug("🍪 looping loading all cookies")
        for cookie in cookies:
            if cookie.get("domain") == ".ilpost.it":
                logging.debug("🍪 adding cookie " + str(cookie))
                send(driver, 'Network.setCookie', params=cookie)
        driver.get("https://www.ilpost.it")
        logging.debug("🍪 waiting for all cookies to be loaded: " + str(len(driver.get_cookies())) + " expected " + str(len(cookies)))
    send(driver, 'Network.disable', params={})

def scrape_episode(podcast_data, refresh=True):
    short_name = podcast_data["short_name"]
    name = podcast_data["name"]
    url = podcast_data["url"]
    description = podcast_data["description"]
    logging.debug("👾 Requested scrape for " + short_name)

    # Don't want to hit the servers too much so I'll try cache the data for at least CACHE_TIME secons (defaults to 12 hours).
    if r.get(short_name) :
        scrape_data = pickle.loads(r.get(short_name))
        now = time.time()
        difference = now - scrape_data["last_change"]
        if difference < CACHE_TIME and scrape_data["episode"] != "NotFound":
            refresh =  False
            logging.debug("Now: " + str(now) + " Data Scraped: " + str(scrape_data["last_change"]) + " difference (" + str(difference) + ") smaller than " + str(CACHE_TIME))
    else:
        scrape_data=False

    if  scrape_data and not refresh:
        response = scrape_data
        logging.debug("👾 Found cached data for " + short_name + " avoiding scrape")
    else:
        logging.debug("⚠️ Need fresh data for " + short_name + " scraping")
        logging.debug("👾 Strarting update_podcast_page")
        logging.debug("👾 Preparing driver update_podcast_page")
        driver = webdriver.Remote(command_executor=SELENIUM_HUB, options=opts)

        logging.debug("👾 Working with the driver!")
        with driver:
            loop_scrape = 0
            while True:
                load_cookies(driver)
                if driver.find_elements(By.CLASS_NAME, "user_icon user_not_logged"):
                    logging.debug("👾 not logged in!!!")
                else:
                    logging.info("ℹ️ Loading page")
                    logging.debug("👾 get " + url)
                    driver.get("https://www.ilpost.it/podcasts/")
                    driver.get(url)
                    logging.debug("👾 Search " + PLAYER_XPATH)
                    elem = driver.find_element(By.XPATH, PLAYER_XPATH)
                    logging.debug("👾 Get URL using data-file")
                    episode_url = elem.get_attribute("data-file")
                    if not episode_url:
                        logging.debug("👾 Failed using data-file")
                        logging.debug("👾 Get URL using src")
                        episode_url = elem.get_attribute("src")
                    if episode_url:
                        logging.debug("👾 Success")
                        break
                    elif loop_scrape > SCRAPE_RETRIES:
                        logging.debug("👾 Failed " + str(loop_scrape) + " times, giving up.")
                        episode_url = "NotFound"
                        break
                    else:
                        logging.debug("👾 Failed using src")
                        loop_scrape = loop_scrape + 1
                        logging.debug("👾 Looping again (Retry " + str(loop_scrape) + ")")
            logging.debug("👾 Found streaming url" + str(episode_url))
            driver.close()
            last_scrape = time.time()
            old_episode_url = (
                "Null" if r.get(short_name + "episode_url") is None else pickle.loads(r.get(short_name + "episode_url"))
            )

            # Se il nuovo episodio é effettivamente nuovo aggiorno l'url e aggiorno la data di rilascio
            if old_episode_url != episode_url:
                r.set(short_name + "episode_url", pickle.dumps(episode_url))
                r.set(short_name + "last_change", pickle.dumps(last_scrape))

            # Aggiorno quando é avvenuto l'ultimo scrape
            response = {
                    "episode": episode_url,
                    "name": name,
                    "short_name": short_name,
                    "description": description,
                    "homepage": url,
                    "last_scrape": last_scrape,
                    "last_change": last_scrape,
                    "description": description
            }
            r.set(short_name, pickle.dumps(response))
    return response

def do_checks():
    """Health Checks"""
    logging.info("Starting Checks")

    logging.info("Check Selenium")
    selenium_status = is_selenium_available()

    # """This test should be runt once in a while. Maybe as initialization"""
    # logging.info("Check Selenium Navigation")
    # selenium_nav_status = is_selenium_working()


    logging.info("Check Redis")
    redis_status = is_redis_available()

    exit_code=0
    ok_code=200
    ko_code=500

    if not selenium_status[0]:
        logging.error("Selenium Failed")
        selenium_state="Connection to Selenium Failed"
        selenium_state_code=ko_code
        exit_code=exit_code+1
    else:
        selenium_state="ok"
        selenium_state_code=ok_code

    if not redis_status:
        logging.error("Redis Failed")
        redis_state = "Connection to Redis Failed"
        redis_state_code=ko_code
        exit_code=exit_code+1
    else:
        redis_state = "ok"
        redis_state_code=ok_code

    if not USERNAME or not PASSWORD:
        logging.error("Credentials Failed")
        creds_state = "Missing credentials"
        creds_state_code=ko_code
        exit_code=exit_code+1
    else:
        creds_state = "ok"
        creds_state_code=ok_code

    message = {
        "selenium": {
            "state": selenium_state,
            "state_code": selenium_state_code
            },
        "redis": {
            "state ": redis_state,
            "state_code": redis_state_code
        },
        "credentials": {
            "state ": creds_state ,
            "state_code": creds_state_code
        }
    }
    logging.info("Finished Checks")
    logging.debug("Exit code " + str(exit_code))
    return exit_code, message

def get_podcast_info(podcast_short_name):
    found = False
    response = { "error": "the podcast does not exist" }
    podcasts = get_podcasts_list()
    for podcast in podcasts:
        if podcast["short_name"] == podcast_short_name:
            response = podcast
            found = True
            break
    if not found:
        podcasts = get_podcasts_list(fresh=true)
        for podcast in podcasts:
            if podcast["short_name"] == podcast_short_name:
                response = podcast
                found = True
                break
    if not found:
        logging.debug("the podcast does not exist")
        response = { "error": "the podcast does not exist" }
    return response

def scrape_all(podcasts):
    response=[]
    for podcast in podcasts:
        response.append(scrape_episode(podcast))
    return response

def get_podcasts_list(fresh=False):
    if r.get("podcasts") and not fresh:
        podcasts = pickle.loads(r.get("podcasts"))
    else:
        """Scrape podcast list"""
        logging.debug("👾 Starting scraping podcasts titles")
        cookies = get_cookies()
        driver = webdriver.Remote(command_executor=SELENIUM_HUB, options=opts)
        logging.debug("👾 Working with the driver!")
        with driver:
            logging.info("Navigate to Morning Post Page")

            logging.debug("👾 get podcasts page")
            driver.get("https://www.ilpost.it/podcasts/")
            find_url="https://www.ilpost.it/episodes/podcasts/"
            logging.debug("👾 find podcasts cards")

            cards = driver.find_elements(By.CLASS_NAME, "card")
            logging.debug("👾 cycle thru " + str(len(cards)) + " cards")
            podcasts = []
            for card in cards:
                description = card.find_element(By.TAG_NAME, "p")
                header = card.find_element(By.TAG_NAME, "h3")
                url = header.find_element(By.TAG_NAME, "a")

                href = url.get_attribute("href")
                name = url.text
                description_txt = description.text
                match = re.search(r'/episodes/podcasts/(.+)/', href)
                short_name=match.group(1)

                logging.debug(description_txt)
                logging.debug(href)
                logging.debug(name)
                logging.debug(short_name)
                podcasts.append({"short_name": short_name, "name": name, "url": href, "description": description_txt})
            print(podcasts)
            driver.close()
            r.set("podcasts", pickle.dumps(podcasts))
    response = podcasts
    return response

@app.api_route("/cookies", response_class=ORJSONResponse)
def get_cookies_json(response: Response):
    """Geneare payload of cookies in json format"""
    checks = do_checks()
    if checks[0] == 0 :
        message = get_cookies()
    else:
        message = checks[1]
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    return message

@app.get("/ping", response_class=PlainTextResponse, status_code=200)
def ping():
    """Pong"""
    return "pong"

@app.get("/status", response_class=ORJSONResponse, status_code=200)
def status_page(response: Response):
    checks = do_checks()
    if checks[0] > 0:
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    return checks[1]

# Scrape the list of the podcasts
@app.api_route('/podcasts', response_class=ORJSONResponse, status_code=200)
def podcasts( request: Request, response: Response, fresh: Union[str, None] = None):
    podcasts = get_podcasts_list(fresh=fresh)
    logging.debug(dir(request))
    for podcast in podcasts:
        podcast["scrape_url"] = str(request.base_url) + "podcast/" + podcast["short_name"]
        if r.get(podcast["short_name"]):
            scrape_data = pickle.loads(r.get(podcast["short_name"]))
            podcast["last_episode"] = scrape_data["episode"]
            podcast["last_scrape"] = scrape_data["last_scrape"]
            podcast["last_change"] = scrape_data["last_change"]

    return podcasts

@app.api_route('/getall', response_class=ORJSONResponse, status_code=200)
def getall():
    podcasts=get_podcasts_list()
    scrape_all(podcasts)
    response = podcasts
    return response

@app.get("/podcast/{podcast_short_name}", response_class=ORJSONResponse, status_code=200)
def scrape_single_podcast(podcast_short_name, refresh: Union[str, None] = None):
    if refresh:
        r.delete(podcast_short_name)
    podcast_data = get_podcast_info(podcast_short_name)
    if "error" in podcast_data:
        response = podcast_data
    else:
        response = scrape_episode(podcast_data)
    return response

@app.get("/", response_class=HTMLResponse, status_code=200)
def main():
    """Main Page"""
    response = "<center><p>Go away sucker</p></center>"
    return response
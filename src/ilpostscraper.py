#!/usr/bin/env python3
"""This stupid webapp catches the latest podcast from ilpost.it ."""
import orjson, json
import os
import pickle
import time
import redis
import requests
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
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from fastapi.security import OAuth2PasswordBearer

# Setup Logging
import logging

LOGLEVEL = os.getenv("LOGLEVEL", "INFO")
_INFO = "\033[92m"  # GREEN
_WARNING = "\033[93m"  # YELLOW
_ERROR = "\033[91m"  # RED
_DEBUG = "\033[95m"  # MAGENTA
_RESET = "\033[0m"  # RESET

logging.basicConfig(
    format="{asctime} [{levelname}] {message}", style="{", level=LOGLEVEL
)
logging.addLevelName(logging.INFO, _INFO + logging.getLevelName(logging.INFO) + _RESET)
logging.addLevelName(
    logging.WARNING, _WARNING + logging.getLevelName(logging.WARNING) + _RESET
)
logging.addLevelName(
    logging.ERROR, _ERROR + logging.getLevelName(logging.ERROR) + _RESET
)
logging.addLevelName(
    logging.DEBUG, _DEBUG + logging.getLevelName(logging.DEBUG) + _RESET
)


def _quit(*vargs, **kwargs):
    logging.error(*vargs, **kwargs)
    raise SystemExit


logging.quit = _quit


# Load Environment Variables from file

load_dotenv()
time.tzset()

USERAGENT = os.getenv(
    "USERAGENT",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36",
)  # Set the user agnet to something credible.
# Values from envirionment
USERNAME = os.getenv("LOGIN_USER")
PASSWORD = os.getenv("LOGIN_PASSWORD")
SELENIUM_URL = os.getenv("SELENIUM_URL", "http://selenium:4444")
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
_1_sec = 1
_12_hours = _1_sec * 60 * 60 * 12
CACHE_TIME = int(os.getenv("CACHE_TIME", _12_hours))
CACHE_TIME = int(os.getenv("CACHE_TIME", "43200"))  # 43200 is 12 hours
CHECK_SITE = os.getenv("CHECK_SITE", "https://www.google.com")
# Used Variables
SELENIUM_HUB = SELENIUM_URL + "/wd/hub"
LOGIN_PAGE = "https://www.ilpost.it/wp-login.php?redirect_to=https://www.ilpost.it"  # Where to start the login.
USERNAME_XPATH = "//input[@id='user_login']"  # Where to put the username
PASSWORD_XPATH = "//input[@id='user_pass']"  # Where to put the password
CHECKBOX_XPATH = "//input[@id='rememberme']"  # Remember me logged Checkbock
LOGIN_XPATH = '//input[@id="wp-submit"]'  # Login Button
PLAYER_XPATH = '//audio[@id="ilpostPlayerAudio"]'  # Where should I look for the mp3?
SCRAPE_RETRIES = int(
    os.getenv("SCRAPE_RETRIES", "10")
)  # how many time do I have to try and retrive the episode? This value should be 1 but the site sucks.
EXPECTED_COOKIES = 3  # ilpost.it uses wordpress that produces a finite number of cookies in this case should be always be 3 or more.

#### Setup Option for the driver
# Initialize the Chrome Browser Options.
opts = Options()
# Let's set a credible UserAgent
opts.add_argument("user-agent=" + USERAGENT)
# We prefer to use /tmp as SHM is a finite resource.
opts.add_argument("disable-dev-shm-usage")

# Init redis Connection
redis_cache = redis.Redis(
    host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, socket_timeout=1
)

# Initialize FastAPI
app = FastAPI()


# Get Cookies from Redis
def get_cookies_redis():
    """Return false if redis has no cookies.
    Otherwise return cookies."""
    logging.debug("Start get_cookies_redis")
    pickled_cookies = redis_cache.get("cookies")
    try:
        cookies = pickle.loads(pickled_cookies)
    except TypeError:
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

    logging.debug("End get_cookies_redis")
    return cookies


# Create Cookies
def create_cookies():
    """Create new cookies on wordpress!"""
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
        while (
            len(cookies) < EXPECTED_COOKIES
        ):  # I need to cicle while the cookies are created. We expect a minimum number of cookies for wordpress
            logging.debug(driver.get_cookies())
            cookies = driver.get_cookies()
            logging.debug(f"Number of cookies saved: {len(driver.get_cookies())}")
        redis_cache.set("cookies", pickle.dumps(cookies))
        logging.debug("End create_cookies")
        return cookies


def is_selenium_available():
    """Check if selenium is available"""
    logging.debug("Getting url " + SELENIUM_HUB + "/status")
    try:
        response = requests.get(SELENIUM_HUB + "/status")
        status = response.status_code
    except requests.exceptions.RequestException as e:
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
    with driver:
        logging.debug("Navigate to " + CHECK_SITE)
        try:
            driver.get(CHECK_SITE)
        except selenium.common.exceptions.WebDriverException as e:
            logging.debug("######### ERRORE NELL'APRIRE IL SITO")
            logging.debug(e.msg)
            raise e
    return "200"


def is_redis_available():
    """Check if redis is ready!"""
    try:
        redis_cache.memory_stats()
    except (
        redis.exceptions.ConnectionError,
        redis.exceptions.BusyLoadingError,
        redis.exceptions.TimeoutError,
    ):
        return False
    return True


def get_cookies():
    """Get cookies or try generating new ones"""
    cookies = get_cookies_redis()
    if not cookies:
        logging.info("Validazione Cookie fallita, avvio la rigenerazione")
        cookies = create_cookies()
    return cookies


# This function is used to send data to a remote driver as it's not supported as a direct command in this configuration
def send(driver, cmd, params={}):
    resource = "/session/%s/chromium/send_command_and_get_result" % driver.session_id
    url = driver.command_executor._url + resource
    body = json.dumps({"cmd": cmd, "params": params})
    response = driver.command_executor._request("POST", url, body)
    return response.get("value")


# Load cookies into driver
def load_cookies(driver):
    cookies = get_cookies()
    logging.debug("Deleting all cookies before adding new ones")
    driver.delete_all_cookies()
    send(driver, "Network.enable", params={})
    while len(driver.get_cookies()) < len(cookies):
        logging.debug(f"looping loading all cookies")
        for cookie in cookies:
            if cookie.get("domain") == ".ilpost.it":
                logging.debug(f"adding cookie {cookie}")
                send(driver, "Network.setCookie", params=cookie)
        driver.get("https://www.ilpost.it")
        logging.debug(
            f"waiting for all cookies to be loaded: %s expected %s",
            len(driver.get_cookies()),
            len(cookies),
        )
    send(driver, "Network.disable", params={})


# Search a specific attribute in an object. If it's not present return False
class element_has_atttribute(object):
    """An expectation for checking that an element has a particular css class.

    locator - used to find the element
    returns the WebElement once it has the particular css class
    """

    def __init__(self, locator, attribute):
        self.locator = locator
        self.attribute = attribute

    def __call__(self, driver):
        element = driver.find_element(*self.locator)  # Finding the referenced element
        for self.attr in element.get_property("attributes"):
            if self.attr["name"] == self.attribute:
                return True
        return False


# Scrape an episode
def scrape_episode(podcast_data, refresh=True):
    short_name = podcast_data["short_name"]
    name = podcast_data["name"]
    url = podcast_data["url"]
    description = podcast_data["description"]
    logging.debug("Requested scrape for " + short_name)

    # Don't want to hit the servers too much so I'll try cache the data for at least CACHE_TIME secons (defaults to 12 hours).
    if redis_cache.get(short_name):
        scrape_data = pickle.loads(redis_cache.get(short_name))
        now = time.time()
        difference = now - scrape_data["last_change"]
        if difference < CACHE_TIME and scrape_data["episode"] != "NotFound":
            refresh = False
            logging.debug(
                f"Now: {now} Data Scraped: {scrape_data['last_change']} difference {difference} smaller than {CACHE_TIME}"
            )
    else:
        scrape_data = False

    if scrape_data and not refresh:
        response = scrape_data
        logging.info(f"Found cached data for {short_name} avoiding scrape")
    else:
        logging.warning(f"Need fresh data for {short_name} scraping")
        driver = webdriver.Remote(command_executor=SELENIUM_HUB, options=opts)
        driver.implicitly_wait(10)
        with driver:
            load_cookies(driver)
            driver.get(url)
            logging.info(f"ℹ️ Scraping page: {url}")
            logging.debug("Search " + PLAYER_XPATH)
            player = driver.find_element(By.XPATH, PLAYER_XPATH)
            logging.debug("Get URL using data-file or src")
            logging.debug(
                f"Searching for src or data-file attribute in {PLAYER_XPATH} on page {url}"
            )
            wait = WebDriverWait(driver, 10)
            wait.until(element_has_atttribute((By.XPATH, PLAYER_XPATH), "src"))
            player = driver.find_element(By.XPATH, PLAYER_XPATH)
            attributes = ["src", "data-file"]
            for attribute in attributes:
                episode_url = player.get_attribute(attribute)
                if "mp3" in episode_url:
                    logging.info(
                        f"Found streaming url {episode_url} looking in attribute {attribute}"
                    )
                    break
                else:
                    logging.error(f"Notthing found in {attribute}: [{episode_url}]")

            last_scrape = time.time()
            old_episode_url = (
                "Null"
                if redis_cache.get(short_name + "episode_url") is None
                else pickle.loads(redis_cache.get(short_name + "episode_url"))
            )

            # Se il nuovo episodio é effettivamente nuovo aggiorno l'url e aggiorno la data di rilascio
            if old_episode_url != episode_url:
                redis_cache.set(short_name + "episode_url", pickle.dumps(episode_url))
                redis_cache.set(short_name + "last_change", pickle.dumps(last_scrape))

            # Aggiorno quando é avvenuto l'ultimo scrape
            response = {
                "episode": episode_url,
                "name": name,
                "short_name": short_name,
                "description": description,
                "homepage": url,
                "last_scrape": last_scrape,
                "last_change": last_scrape,
                "description": description,
            }
            redis_cache.set(short_name, pickle.dumps(response))
    return response


def do_checks():
    """Health Checks"""
    logging.info("Starting Checks")
    logging.info("Check Selenium")
    selenium_status = is_selenium_available()
    logging.info("Check Redis")
    redis_status = is_redis_available()

    exit_code = 0
    ok_code = 200
    ko_code = 500

    if not selenium_status[0]:
        logging.error("Selenium Failed")
        selenium_state = "Connection to Selenium Failed"
        selenium_state_code = ko_code
        exit_code = exit_code + 1
    else:
        selenium_state = "ok"
        selenium_state_code = ok_code

    if not redis_status:
        logging.error("Redis Failed")
        redis_state = "Connection to Redis Failed"
        redis_state_code = ko_code
        exit_code = exit_code + 1
    else:
        redis_state = "ok"
        redis_state_code = ok_code

    if not USERNAME or not PASSWORD:
        logging.error("Credentials Failed")
        creds_state = "Missing credentials"
        creds_state_code = ko_code
        exit_code = exit_code + 1
    else:
        creds_state = "ok"
        creds_state_code = ok_code

    message = {
        "selenium": {"state": selenium_state, "state_code": selenium_state_code},
        "redis": {"state ": redis_state, "state_code": redis_state_code},
        "credentials": {"state ": creds_state, "state_code": creds_state_code},
    }

    logging.info("Finished Checks")
    logging.debug("Exit code {exit_code}")
    return exit_code, message


def get_podcast_info(podcast_short_name):
    found = False
    response = {"error": "the podcast does not exist"}
    podcasts = get_podcasts_list()
    for podcast in podcasts:
        if podcast["short_name"] == podcast_short_name:
            response = podcast
            found = True
            break
    if not found:
        podcasts = get_podcasts_list(fresh=True)
        for podcast in podcasts:
            if podcast["short_name"] == podcast_short_name:
                response = podcast
                found = True
                break
    if not found:
        logging.error("The podcast does not exist")
        response = {"error": "the podcast does not exist"}
    return response


# Get all the podcasts
def get_podcasts_list(fresh=False):
    logging.debug("Getting podcasts")
    if redis_cache.get("podcasts") and not fresh:
        logging.debug("Skipping scrape and using data from redis")
        podcasts = pickle.loads(redis_cache.get("podcasts"))
    else:
        """Scrape podcast list"""
        logging.debug("Starting scraping podcasts titles")
        driver = webdriver.Remote(command_executor=SELENIUM_HUB, options=opts)
        with driver:
            logging.debug("Get podcasts page to scrape all the podcasts")
            find_url = "https://www.ilpost.it/podcasts/"
            logging.debug("find podcasts cards")
            driver.get(find_url)
            cards = driver.find_elements(By.CLASS_NAME, "card")
            logging.debug(f"cycle thru {len(cards)} cards")
            podcasts = []
            for card in cards:
                description = card.find_element(By.TAG_NAME, "p")
                header = card.find_element(By.TAG_NAME, "h3")
                url = header.find_element(By.TAG_NAME, "a")

                href = url.get_attribute("href")
                name = url.text
                description_txt = description.text
                match = re.search(r"/episodes/podcasts/(.+)/", href)
                short_name = match.group(1)

                logging.debug(description_txt)
                logging.debug(href)
                logging.debug(name)
                logging.debug(short_name)
                podcasts.append(
                    {
                        "short_name": short_name,
                        "name": name,
                        "url": href,
                        "description": description_txt,
                    }
                )
            print(podcasts)
            redis_cache.set("podcasts", pickle.dumps(podcasts))
    response = podcasts
    return response


@app.api_route("/cookies", response_class=ORJSONResponse)
def get_cookies_json(response: Response):
    """Geneare payload of cookies in json format"""
    checks = do_checks()
    if checks[0] == 0:
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
@app.api_route("/podcasts", response_class=ORJSONResponse, status_code=200)
def podcasts(request: Request, response: Response, fresh: Union[str, None] = None):
    podcasts = get_podcasts_list(fresh=fresh)
    for podcast in podcasts:
        podcast["scrape_url"] = f"{request.base_url}podcast/{podcast['short_name']}"
        if redis_cache.get(podcast["short_name"]):
            scrape_data = pickle.loads(redis_cache.get(podcast["short_name"]))
            podcast["last_episode"] = scrape_data["episode"]
            podcast["last_scrape"] = scrape_data["last_scrape"]
            podcast["last_change"] = scrape_data["last_change"]

    return podcasts


@app.api_route("/getall", response_class=ORJSONResponse, status_code=200)
def getall():
    response = [scrape_episode(podcast) for podcast in get_podcasts_list()]
    return response


@app.get(
    "/podcast/{podcast_short_name}", response_class=ORJSONResponse, status_code=200
)
def scrape_single_podcast(podcast_short_name, refresh: Union[str, None] = None):
    if refresh:
        redis_cache.delete(podcast_short_name)
    podcast_data = get_podcast_info(podcast_short_name)
    if "error" in podcast_data:
        response = podcast_data
    else:
        response = scrape_episode(podcast_data)
    return response


@app.get("/", response_class=HTMLResponse, status_code=200)
def main():
    response = "<center><p>Go away sucker</p></center>"
    return response

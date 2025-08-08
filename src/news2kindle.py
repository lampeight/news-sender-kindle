#!/usr/bin/env python
# encoding: utf-8

# idea and original code from from from https://gist.github.com/alexwlchan/01cec115a6f51d35ab26

# PYTHON boilerplate
from email.utils import COMMASPACE, formatdate
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
import smtplib
import morss
import sys
import pypandoc
import pytz
from tzlocal import get_localzone
import time
import logging
import threading
import subprocess
from datetime import datetime, timedelta
import os
import feedparser
from FeedparserThread import FeedparserThread

logging.basicConfig(level=logging.INFO)

EPUB_TITLE = os.getcwd("TITLE")
EMAIL_SMTP = os.getenv("EMAIL_SMTP")
EMAIL_SMTP_PORT = int(os.getenv("EMAIL_SMTP_PORT"))
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASSWD = os.getenv("EMAIL_PASSWORD")
EMAIL_FROM = os.getenv("EMAIL_FROM")
KINDLE_EMAIL = os.getenv("KINDLE_EMAIL")
PANDOC = os.getenv("PANDOC_PATH", "/usr/bin/pandoc")
PERIOD = int(os.getenv("UPDATE_PERIOD", 24))  # hours between RSS pulls
FETCH_PERIOD=int(os.getenv("FETCH_PERIOD",24))
HOUR=int(os.getenv("HOUR",0))
MINUTE=int(os.getenv("MINUTES",0))
ENCRYPTION = os.getenv("ENCRYPTION")

FEED_FILE = '/config/feeds.txt'
COVER_FILE = '/config/cover.png'


feed_file = os.path.expanduser(FEED_FILE)

def load_feeds():
    """Return a list of the feeds for download.
        At the moment, it reads it from `feed_file`.
    """
    with open(feed_file, 'r') as f:
        return list(f)


def update_start(now):
    """
    Update the timestamp of the feed file. The time stamp is used
    as the starting point to download articles.
    """
    new_now = time.mktime(now.timetuple())
    with open(feed_file, 'a'):
        os.utime(feed_file, (new_now, new_now))


def get_start(fname):
    """
    Get the starting time to read posts since. This is currently saved as 
    the timestamp of the feeds file.
    """
    return pytz.utc.localize(datetime.fromtimestamp(os.path.getmtime(fname))) - timedelta(hours=FETCH_PERIOD)


def get_posts_list(feed_list, START):
    """
    Spawn a worker thread for each feed.
    """
    posts = []
    ths = []
    lock = threading.Lock()

    def append_posts(new_posts):
        lock.acquire()
        posts.extend(new_posts)
        lock.release()

    for link in feed_list:
        url = str(link)
        options = morss.Options(format='rss')
        url, rss = morss.FeedFetch(url, options)
        rss = morss.FeedGather(rss, url, options)
        output = morss.FeedFormat(rss, options, 'unicode')
        feed = feedparser.parse(output)
        th = FeedparserThread(feed, START, append_posts)
        ths.append(th)
        th.start()

    for th in ths:
        th.join()

    # When all is said and done,
    return posts


def nicedate(dt):
    return dt.strftime('%d %B %Y').strip('0')


def nicehour(dt):
    return dt.strftime('%I:%M&thinsp;%p').strip('0').lower()


def nicepost(post):
    thispost = post._asdict()
    thispost['nicedate'] = nicedate(thispost['time'])
    thispost['nicetime'] = nicehour(thispost['time'])
    return thispost

def generate_dynamic_cover(base_cover_path, output_path):
    # Load image
    img = Image.open(base_cover_path).convert('RGBA')
    draw = ImageDraw.Draw(img)

    # Build date string
    today_str = datetime.now().strftime('%A %d %B %Y')

    # Load font (adjust path & size if needed)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 40)
    except IOError:
        font = ImageFont.load_default()

    # Measure text size using textbbox (Pillow 8.0+)
    bbox = draw.textbbox((0, 0), today_str, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    # Position text at the bottom center
    x = (img.width - text_w) / 2
    y = img.height - text_h - 250  # 50px from bottom

    # Draw text
    draw.text((x, y), today_str, font=font, fill="black")

    # Save to output path
    img.save(output_path)


# Load CSS from ./config/style.css
css_path = Path("./config/style.css")
if css_path.exists():
    css_content = css_path.read_text(encoding="utf-8")
else:
    css_content = ""  # fallback if file missing

html_head = f"""<html>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width" />
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="apple-mobile-web-app-capable" content="yes" />
<style>
{css_content}
</style>
<title>{EPUB_TITLE}</title>
</head>
<body>
"""

html_tail = u"""
</body>
</html>
"""

html_perpost = u"""
    <article>
        <h1><a href="{link}">{title}</a></h1>
        <p><small>By {author} for <i>{blog}</i>, on {nicedate} at {nicetime}.</small></p>
         {body}
    </article>
"""


def send_mail(send_from, send_to, subject, text, files):
    # assert isinstance(send_to, list)

    msg = MIMEMultipart()
    msg['From'] = send_from
    msg['To'] = COMMASPACE.join(send_to)
    msg['Date'] = formatdate(localtime=True)
    msg['Subject'] = subject
    msg.attach(MIMEText(text, 'text', 'utf-8'))

    for f in files or []:
        with open(f, "rb") as fil:
            msg.attach(MIMEApplication(
                fil.read(),
                Content_Disposition=f'attachment; filename="{os.path.basename(f)}"',
                Name=os.path.basename(f)
            ))
    if ENCRYPTION == "SSL":
        smtp = smtplib.SMTP_SSL(EMAIL_SMTP, EMAIL_SMTP_PORT)
    elif ENCRYPTION == "TLS":
        smtp = smtplib.SMTP(EMAIL_SMTP, EMAIL_SMTP_PORT)
        smtp.ehlo()
        smtp.starttls()
    else:
        sys.exit("ENCRYPTION TYPE NOT FOUND !")

    smtp.login(EMAIL_USER, EMAIL_PASSWD)
    smtp.sendmail(send_from, send_to, msg.as_string())
    smtp.quit()


def convert_ebook(input_file, output_file):
    cmd = ['ebook-convert', input_file, output_file]
    process = subprocess.Popen(cmd)
    process.wait()


def do_one_round():
    # get all posts from starting point to now
    now = pytz.utc.localize(datetime.now())
    #midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = get_start(feed_file)

    logging.info(f"Collecting posts since {start}")

    posts = get_posts_list(load_feeds(), start)
    posts.sort()

    logging.info(f"Downloaded {len(posts)} posts")

    if posts:
        logging.info("Compiling newspaper")
        temp_cover = '/tmp/cover_with_date.png'
        generate_dynamic_cover(COVER_FILE, temp_cover)
        result = html_head + \
            u"\n".join([html_perpost.format(**nicepost(post))
                        for post in posts]) + html_tail

        logging.info("Creating epub")
        today_date = datetime.today().date()
        epubFile = str(today_date)+'.epub'
        mobiFile = str(today_date)+'.mobi'
        os.environ['PYPANDOC_PANDOC'] = PANDOC

        pypandoc.convert_text(result,
                              to='epub3',
                              format="html",
                              outputfile=epubFile,
                              extra_args=["--standalone",
                                        #   "--css={css_path}",
                                          "--toc",
                                          "--toc-depth=1",
                                          f"--epub-cover-image={temp_cover}"
                                          ])
        convert_ebook(epubFile, mobiFile)
        epubFile_2 = str(EPUB_TITLE)+' - '+str(today_date)+'.epub'
        convert_ebook(mobiFile, epubFile_2)

        logging.info("Sending to kindle email")
        send_mail(send_from=EMAIL_FROM,
                  send_to=[KINDLE_EMAIL],
                  subject=str(EPUB_TITLE)+" - "+str(today_date),
                  text="Hot off the press!\n\n--\n\n",
                  files=[epubFile_2])
        logging.info("Cleaning up...")
        os.remove(epubFile)
        os.remove(mobiFile)

    logging.info("Finished.")
    update_start(now)

def get_next_x_am():
    tz = get_localzone()
    timezone=pytz.timezone(tz.key)
    now = datetime.now(tz=timezone)
    next_x_am = now.replace(hour=HOUR, minute=MINUTE, second=0, microsecond=0)
    if now >= next_x_am:
        next_x_am += timedelta(days=1)
    return (next_x_am - now).total_seconds()

if __name__ == '__main__':
    while True:
        do_one_round()
        seconds = get_next_x_am()
        # seconds = PERIOD*3600
        time.sleep(seconds)
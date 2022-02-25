import requests
import configparser
import os
import re
import sqlite3
from install import build_sqlite_db
from lxml import etree
import webbrowser
import threading
import binascii
from urllib.parse import quote
from queue import Queue

CONFIG_FILE = "config.ini"
CONFIG_FILE_DEFAULT = "config.ini.default"
CONFIG = configparser.ConfigParser()

CONFIG_NAME_LIST = [
    "base.avmoo_site",
    "base.db_file",
    "base.country",

    "spider.sleep",
    "spider.insert_threshold",
    "spider.continued_skip_limit",

    "requests.timeout",
    "requests.user_agent",

    "website.cdn",
    "website.page_limit",
    "website.actresses_page_limit",
    "website.group_page_limit",
    "website.group_page_order_by",
    "website.use_cache",
    "website.auto_open_site_on_run",
]

DB = {}

NETWORK_CONNECT = False

COUNTRY_MAP = {
    'en': 'English',
    'ja': '日本语',
    'tw': '正體中文',
    'cn': '简体中文',
}

ESCAPT_LIST = (
    ("/", "//"),
    ("'", "''"),
    ("[", "/["),
    ("]", "/]"),
    ("%", "/%"),
    ("&", "/&"),
    ("_", "/_"),
    ("(", "/("),
    (")", "/)"),
)

LOCAL_IP = "127.0.0.1"
DEFAULT_PORT = 5000

DATA_STORAGE = {
    "av_genre": [],
    "av_stars": [],
    "av_extend": [],
}

# 缓存
SQL_CACHE = {}

# 任务队列
QUEUE = Queue(maxsize=0)

def init():
    print("common.init")
    global CONFIG, DB, NETWORK_CONNECT, STATIC_FILE
    # 初始化配置
    config_check()
    config_init()

    # 初始化db
    DB['CONN'] = sqlite3.connect(CONFIG.get(
        "base", "db_file"), check_same_thread=False)
    DB['CUR'] = DB['CONN'].cursor()
    
    # 如果不存在则新建表
    build_sqlite_db(DB['CONN'], DB['CUR'])
    print("common.init.db")
    
    # 打开主页
    if CONFIG.getboolean("website", "auto_open_site_on_run"):
        open_browser_tab(get_local_url())


def storege_init(table: str) -> None:
    global DATA_STORAGE
    if table not in DATA_STORAGE:
        DATA_STORAGE[table] = fetchall("SELECT * FROM " + table)

def storage(table: str, cond: dict) -> list:
    global DATA_STORAGE
    storege_init(table)
    return [x for x in DATA_STORAGE[table] if [1 for y in cond if x[y] in cond[y]]]


def storage_col(table: str, cond: dict, col: str) -> list:
    global DATA_STORAGE
    storege_init(table)
    return [x[col] for x in DATA_STORAGE[table] if [1 for y in cond if x[y] in cond[y]]]


def config_path() -> str:
    global CONFIG_FILE, CONFIG_FILE_DEFAULT
    if os.path.exists(CONFIG_FILE):
        return CONFIG_FILE
    return CONFIG_FILE_DEFAULT


def config_init() -> None:
    global CONFIG, COUNTRY_MAP
    # 初始化配置
    CONFIG.read(config_path())
    CONFIG.set("base", "country_name", COUNTRY_MAP[CONFIG.get("base", "country")])


def config_check():
    global CONFIG_FILE, CONFIG_FILE_DEFAULT
    if not os.path.exists(CONFIG_FILE):
        return
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)
    config_default = configparser.ConfigParser()
    config_default.read(CONFIG_FILE_DEFAULT)
    for (section, option) in [x.split('.') for x in CONFIG_NAME_LIST]:
        if not config.has_section(section):
            config.add_section(section)
        if not config.has_option(section, option):
            config.set(section, option, config_default.get(section, option))
    config_save(config)


def config_save(config):
    global CONFIG_FILE
    if config.has_option("base", "country_name"):
        config.remove_option("base", "country_name")
    with open(CONFIG_FILE, "w") as fp:
        config.write(fp)


def insert_sql_build(table: str, data: dict) -> str:
    sql = "REPLACE INTO {} ({}) VALUES ({})".format(
        table, ','.join(list(data)), ("?," * len(data))[:-1]
    )
    return sql


# 插入sql
def insert(table: str, data: list):
    global DB
    if not data:
        return
    sql = insert_sql_build(table, data[0])
    print("SQL INSERT:{}".format(sql))
    DB['CUR'].executemany(sql, [tuple(x.values()) for x in data])
    DB['CONN'].commit()


# 执行sql
def execute(sql):
    global DB
    print("SQL EXEC:{}".format(sql))
    DB['CUR'].execute(sql)
    DB['CONN'].commit()


# 查询sql
def fetchall(sql) -> list:
    global DB
    DB["CUR"].execute(sql)
    rows = DB["CUR"].fetchall()
    if not rows:
        return []
    
    result = []
    for row in rows:
        row_dict = {}
        for i in range(len(DB["CUR"].description)):
            row_dict[DB["CUR"].description[i][0]] = row[i]
        result.append(row_dict)
    return result


def get_new_avmoo_site() -> str:
    res = requests.get('https://tellme.pw/avmoo')
    html = etree.HTML(res.text)
    avmoo_site = html.xpath(
        '/html/body/div[1]/div[2]/div/div[2]/h4[1]/strong/a/@href')[0]
    return avmoo_site


def list_in_str(target_list: tuple, target_string: str) -> bool:
    for item in target_list:
        if item in target_string:
            return True
    return False


def get_url(page_type: str = "", keyword: str = "", page_no: int = 1) -> str:
    global CONFIG
    ret = '{}/{}'.format(CONFIG.get("base", "avmoo_site"),
                         CONFIG.get("base", "country"), )
    if page_type == "search":
        if keyword != "":
            ret += '/{}/{}'.format(page_type, keyword)
    else:
        if page_type != "":
            ret += '/{}'.format(page_type)
        if keyword != "":
            ret += '/{}'.format(keyword)
    if page_no > 1:
        ret += '/page/{}'.format(page_no)
    return ret


def get_local_url(page_type: str = "", keyword: str = "", page_no: int = 1) -> str:
    ret = 'http://{}:{}'.format(LOCAL_IP, DEFAULT_PORT)
    if page_type != "":
        ret += '/{}'.format(page_type)
    if keyword != "":
        ret += '/{}'.format(quote(keyword))
    if page_no > 1:
        ret += '/page/{}'.format(page_no)
    return ret


def search_where(key_item: str) -> str:
    key_item = sql_escape(key_item)
    return "(av_list.title LIKE '%{0}%' OR ".format(key_item) + \
           "av_list.director = '{0}' OR ".format(key_item) + \
           "av_list.studio = '{0}' OR ".format(key_item) + \
           "av_list.label = '{0}' OR ".format(key_item) + \
           "av_list.series LIKE '%{0}%' OR ".format(key_item) + \
           "av_list.genre LIKE '%|{0}|%' OR ".format(key_item) + \
           "av_list.stars LIKE '%{0}%')".format(key_item)


def open_browser_tab(url):
    print("open_browser_tab:", url)

    def _open_tab(url_param):
        webbrowser.open_new_tab(url_param)

    thread = threading.Thread(target=_open_tab, args=(url,))
    thread.daemon = True
    thread.start()


def sql_escape(keyword: str) -> str:
    for item in ESCAPT_LIST:
        keyword = keyword.replace(item[0], item[1])
    return keyword


def parse_url(url: str) -> tuple:
    if url is None or url == "":
        return "", "", -1
    res = re.findall(
        "https?://[^/]+/[^/]+/(movie|star|genre|series|studio|label|director|search)/([^/]+)(/page/(\\d+))?", url)
    if len(res) == 0:
        print("wrong url:{}".format(url))
        return "", "", -1
    page_start = 1
    if res[0][3] != "":
        page_start = int(res[0][3])
    return res[0][0], res[0][1], page_start


def get_exist_linkid(page_type: str, keyword: str) -> dict:
    sql = ''
    exist_linkid_dict = {}
    # 查询已存在的
    if page_type in ['director', 'studio', 'label', 'series']:
        sql = "SELECT linkid FROM av_list WHERE {}_url='{}'".format(page_type, keyword)
    if page_type == 'genre':
        genre = fetchall("SELECT * FROM av_genre WHERE linkid='{}'".format(keyword))
        if genre:
            sql = "SELECT linkid FROM av_list WHERE genre LIKE '%|{}|%'".format(genre[0]['name'])
    if page_type == 'star':
        sql = "SELECT linkid FROM av_list WHERE stars_url LIKE '%{}%'".format(keyword)
    if page_type == 'group':
        sql = "SELECT linkid FROM av_list WHERE av_id LIKE '{}-%'".format(keyword)
    if page_type == 'search':
        where = []
        for key_item in keyword.split(' '):
            where.append(search_where(key_item))
        sql = "SELECT linkid FROM av_list WHERE " + " AND ".join(where)
    if sql != '':
        ret = fetchall(sql)
        exist_linkid_dict = {x["linkid"]: True for x in ret}
    return exist_linkid_dict


# 获取sql中的表名
def get_table_name(sql):
    return list(set(re.findall("(av_[a-z]+)", sql)))


# 获取缓存key
def gen_cache_key(sql):
    return '|'.join(get_table_name(sql)) + ':' + str(binascii.crc32(sql.encode()) & 0xffffffff)


# 查询sql
def query_sql(sql, if_cache=True) -> list:
    cache_key = gen_cache_key(sql)
    # 是否使用缓存
    if CONFIG.getboolean("website", "use_cache") and if_cache:
        # 是否有缓存
        if cache_key in SQL_CACHE.keys():
            print('SQL CACHE[{}]'.format(cache_key))
            return SQL_CACHE[cache_key][:]
        else:
            print('SQL EXEC[{}]:{}'.format(cache_key, sql))
            ret = fetchall(sql)
            if CONFIG.getboolean("website", "use_cache") and ret != []:
                SQL_CACHE[cache_key] = ret
            return ret[:]
    else:
        print('SQL EXEC:{}'.format(sql))
        return fetchall(sql)

if __name__ == "__main__":
    # test
    init()
    print(DATA_STORAGE)
    print("test:", storage("av_genre", {"name":["企画"]}))
    print("test:", storage("av_genre", {"linkid":["1f0ed55a63eecde5"]}))
    print("test:", storage("av_genre", {"title":["类别"]}))
    print("test:", storage_col("av_genre", {"title":["类别"]}, "linkid"))
    print("test:", storage_col("av_genre", {"title":["类别"]}, "name"))
    
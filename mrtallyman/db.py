import pymysql
import os

from .decorators import memoize
from .utilities import team_log
from .slack import get_bot_by_token
from contextlib import contextmanager
from flask import current_app, g
from pymysql.err import ProgrammingError
from slackclient import SlackClient

@contextmanager
def db_cursor():
    db = pymysql.connect(
        host=os.environ.get('MYSQL_HOST', '127.0.0.1'),
        user=os.environ.get('MYSQL_USER'),
        password=os.environ.get('MYSQL_PASSWORD'),
        db=os.environ.get('MYSQL_DB'),
        autocommit=True,
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor)
    db.show_warnings()

    yield db.cursor()

    db.close()

def get_table_name(suffix):
    return 'team_%s' % suffix

def get_bot_token(team_id):
    team = get_team_config(team_id)

    if team:
        return team['bot_token']

def create_config_table():
    table_name = get_table_name('config')

    if table_exists(table_name):
        return

    sql = '''
    CREATE TABLE `%s` (
        `id` varchar(255) not null,
        `name` varchar(255),
        `access_token` varchar(255),
        `bot_token` varchar(255),
        primary key (`id`),
        unique key (`name`)
    );''' % get_table_name('config')

    with db_cursor() as cursor:
        cursor.execute(sql)

def create_team_table(team_id, channel=None):
    table_name = get_table_name(team_id)

    if table_exists(table_name):
        return

    team_log(team_id, 'Creating table %s' % table_name, channel)

    sql = '''
    CREATE TABLE `%s` (
        `id` int auto_increment,
        `team_id` varchar(255) not null,
        `user_id` varchar(255) not null,
        `given` int default 0 not null,
        `received` int default 0 not null,
        `trolls` int default 0 not null,
        primary key (`id`),
        unique key (`team_id`, `user_id`),
        foreign key (`team_id`) references `team_config`(`id`)
    );''' % table_name

    with db_cursor() as cursor:
        cursor.execute(sql)

    team_log(team_id, 'Table %s created' % table_name, channel)

def get_team_config(team_id):
    sql = 'SELECT * FROM `team_config` WHERE `id` = %s'

    with db_cursor() as cursor:
        cursor.execute(sql, (team_id,))
        return cursor.fetchone()

def get_team_user(team_id, user_id):
    sql = 'SELECT * FROM `team_%s`' % team_id + ' WHERE `user_id` = %s'

    with db_cursor() as cursor:
        cursor.execute(sql, (user_id,))
        return cursor.fetchone()

def get_team_users(team_id):
    sql = 'SELECT * FROM `team_%s`' % team_id

    with db_cursor() as cursor:
        cursor.execute(sql)
        return cursor.fetchall()

def update_team_user(team_id, user_id, attribute, value):
    user = get_team_user(team_id, user_id)

    if user:
        user[attribute] = max(0, user[attribute] + value)

        sql = 'UPDATE `team_%s` SET `%s`' % (team_id, attribute) + ' = %s WHERE `user_id` = %s'
        args = (user[attribute], user_id)

        with db_cursor() as cursor:
            cursor.execute(sql, args)
    else:
        user = create_team_user(team_id, user_id, **{attribute: max(0, value)})

    return user

def create_team_user(team_id, user_id, **attrs):
    user = {
        'team_id': team_id,
        'user_id': user_id,
        'given': 0,
        'received': 0,
        'trolls': 0
    }
    user.update(attrs)

    sql = 'INSERT INTO `team_%s`' % team_id + ' (`team_id`, `user_id`, `given`, `received`, `trolls`) values (%(team_id)s, %(user_id)s, %(given)s, %(received)s, %(trolls)s)'

    with db_cursor() as cursor:
        cursor.execute(sql, user)

    return user

def delete_team_user(team_id, user_id):
    sql = 'DELETE FROM `team_%s`' % team_id + ' WHERE `user_id` = %s'

    with db_cursor() as cursor:
        cursor.execute(sql, (user_id,))

def update_team_config(team_id, **attrs):
    team = get_team_config(team_id)

    if team:
        sql = 'UPDATE `team_config` SET ' + ', '.join([f'`{key}` = %({key})s' for key in attrs.keys()]) + ' WHERE `id` = %(id)s'
        args = attrs
        args['id'] = team_id
    else:
        sql = 'INSERT INTO `team_config` (id, name, access_token, bot_token) values (%(id)s, %(name)s, %(access_token)s, %(bot_token)s)'
        team = {
            'id': team_id,
            'name': '',
            'access_token': '',
            'bot_token': '',
        }
        args = team
        args.update(attrs)

    with db_cursor() as cursor:
        cursor.execute(sql, args)

    team.update(attrs)

    return team

def table_exists(table_name):
    sql = 'SELECT 1 FROM `%s` LIMIT 1' % table_name
    try:
        with db_cursor() as cursor:
            cursor.execute(sql)
        return True
    except ProgrammingError as exc:
        if exc.args[0] == 1146:
            return False
        raise exc

def delete_config_table():
    table_name = get_table_name('config')

    if not table_exists(table_name):
        app_log('Table %s is not there' % table_name)
        return

    sql = 'DROP TABLE `%s`' % table_name

    with db_cursor() as cursor:
        cursor.execute(sql)

    app_log('Table %s deleted' % table_name)

def delete_team_table(team_id, channel):
    table_name = get_table_name(team_id)

    if not table_exists(table_name):
        team_log(team_id, 'Table %s is not there' % table_name, channel)
        return

    sql = 'DROP TABLE `%s`' % table_name

    with db_cursor() as cursor:
        cursor.execute(sql)

    team_log(team_id, 'Table %s deleted' % table_name, channel)

def init_db(app):
    create_config_table()

    token = os.environ['SLACK_API_TOKEN']
    bot = get_bot_by_token(token)
    create_team_table(bot['team_id'])
    update_team_config(bot['team_id'], name=bot['team'], bot_token=token)
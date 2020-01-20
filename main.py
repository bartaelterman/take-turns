# Purpose of this app:
#
# A set of people decide to _take turns_ for something (for my purpose, it's a group of colleagues
# weekly buying a treat for each other).
# The app keeps the usernames of the people in the assignment and the dates when everyone
# is expected to take turn.
#
# The following endpoints are available:
# - /: Get all users and assignment dates, ordered by date
# - /users/<username>:
#     * GET: Get the assignment date for a given user,
#     * PUT: Add a new user to the group,
#     * DELETE: Remove a user from the group and correct the dates for the remaining users
# - /new: Start a new assignment (reset all dates)
# - /lookup: Search for users that are assigned at a given period of time (default: next)
# - /delay: Delay assignment dates
# - /swap: Swap to users assignment dates

from flask import abort, Flask, request
from google.cloud import storage
from google.api_core.exceptions import NotFound
import datetime
import json
import os


BUCKET = os.environ.get('GCS_BUCKET')
DATAFILE = os.environ.get('GCS_OBJECT_NAME', 'data.json')
ASSIGNMENT_WEEKDAY_START = os.environ.get('ASSIGNMENT_WEEKDAY_START', 0)
ASSIGNMENT_INTERVAL_DAYS = os.environ.get('ASSIGNMENT_INTERVAL_DAYS', 7)
ALLOW_ASSIGNMENT_TO_START_TODAY = os.environ.get('ALLOW_ASSIGNMENT_TO_START_TODAY', False)
CLIENT = None


app = Flask(__name__)

USERS = []
DATES = []


def get_first_assignment_date():
    today = datetime.date.today()
    diff_days = (ASSIGNMENT_WEEKDAY_START - today.weekday()) % ASSIGNMENT_INTERVAL_DAYS
    if diff_days == 0 and not ALLOW_ASSIGNMENT_TO_START_TODAY:
        diff_days = ASSIGNMENT_INTERVAL_DAYS  # don't start an assignment today
    assignment_start_date = today + datetime.timedelta(diff_days)
    return assignment_start_date


def initialize_assignment(users_list):
    users = users_list
    start_date = get_first_assignment_date()
    dates = []
    for i in range(len(users)):
        dates.append(start_date + datetime.timedelta(days = i * ASSIGNMENT_INTERVAL_DAYS))
    return users, dates


def serialize_dates(dates_list):
    return [x.isoformat() for x in dates_list]


def deserialize_dates(dates_list):
    return [datetime.date.fromisoformat(x) for x in dates_list]


def serialize_data(users, dates, wide=True):
    return {
        'assignments': data_to_dict(users, dates, wide=wide)
    }


def deserialize_data(input_str):
    users = list(json.loads(input_str)['assignments'].keys())
    dates_str = list(json.loads(input_str)['assignments'].values())
    dates = deserialize_dates(dates_str)
    return users, dates


def read_data():
    global CLIENT
    if BUCKET:
        if not CLIENT:
            CLIENT = storage.Client()
        bucket = CLIENT.get_bucket(BUCKET)
        blob = bucket.blob(DATAFILE)
        try:
            return deserialize_data(blob.download_as_string())
        except NotFound as e:
            return [], []
    else:
        try:
            with open(DATAFILE) as f:
                return deserialize_data(f.read())
        except FileNotFoundError as e:
            return [], []


def save_data(users, dates):
    global CLIENT
    file_content = json.dumps(serialize_data(users, dates, wide=False))
    if BUCKET:
        if not CLIENT:
            CLIENT = storage.Client()
        bucket = CLIENT.get_bucket(BUCKET)
        blob = bucket.blob(DATAFILE)
        blob.upload_from_string(file_content)
    else:
        with open(DATAFILE, 'w+') as out:
            out.write(file_content)


def data_to_dict(users, dates, wide):
    """
    Create a dictionary from the users and dates lists with usernames as keys and dates as values
    """
    s_dates = serialize_dates(dates)
    if wide:
        out = [{'name': name, 'date': date} for name, date in zip(users, s_dates)]
    else:
        out = dict(zip(users, s_dates))
    return out


def to_date(str):
    return datetime.date.fromisoformat(str)


def get_user(username):
    global USERS
    global DATES
    data_dict = data_to_dict(USERS, DATES, wide=False)
    return [username], [data_dict[username]]


def add_user(username):
    global USERS
    global DATES
    USERS.append(username)
    if len(DATES) > 0:
        DATES.append(DATES[-1] + datetime.timedelta(ASSIGNMENT_INTERVAL_DAYS))
    else:
        DATES = [get_first_assignment_date()]
    save_data(USERS, DATES)


def delete_user(username):
    global USERS
    global DATES
    users, dates = get_user(username)
    assignment_date = dates[0]

    # if assignment is already past, remove date from the beginning of the dates list,
    # otherwise remove a date from the end of the dates list
    if assignment_date <= datetime.date.today():
        DATES = DATES[1:]
    else:
        DATES = DATES[:-1]
    USERS.remove(username)
    save_data(USERS, DATES)


def regenerate(users):
    global USERS
    global DATES
    USERS, DATES = initialize_assignment(users)
    save_data(USERS, DATES)


def lookup(period_begin, period_end):
    global USERS
    global DATES
    try:
        index_begin = next(i for i, date in enumerate(DATES) if date >= period_begin)
    except StopIteration:
        return [], []

    if not period_end:
        _users = [USERS[index_begin]]
        _dates = [DATES[index_begin]]
    else:
        index_end = next(i for i, date in enumerate(DATES) if date > period_end)
        _users = USERS[index_begin:index_end]
        _dates = DATES[index_begin:index_end]
    return _users, _dates


def delay(delay_all, delay_days):
    global DATES
    global USERS
    next_index = next(i for i, date in enumerate(DATES) if date > datetime.date.today())
    if delay_all:
        # Delay all: delay all assignments from next to end with delay days
        delayed_dates = [x + datetime.timedelta(days=delay_days) for x in DATES[next_index:]]
        DATES = DATES[:next_index] + delayed_dates
    else:
        # Delay next: only delay the next assignment (the delayed day should still be before the next one)
        if next_index == len(DATES) - 1:
            # the next item is the last -> there is no issue with other assignments. Just delay the last one
            DATES = DATES[:next_index] + [DATES[next_index] + datetime.timedelta(days=delay_days)]
        else:
            # You can only delay up until the next assignment. Not beyond
            day_to_delay = DATES[next_index]
            day_after = DATES[next_index + 1]
            if delay_days >= (day_after - day_to_delay).days:
                abort(400)
            else:
                DATES = DATES[:next_index] + [DATES[next_index] + datetime.timedelta(days=delay_days)] + DATES[next_index+1:]
    save_data(USERS, DATES)


def swap(user_1, user_2):
    global USERS
    global DATES
    user_1_index = USERS.index(user_1)
    user_2_index = USERS.index(user_2)
    USERS[user_2_index], USERS[user_1_index] = USERS[user_1_index], USERS[user_2_index]
    save_data(USERS, DATES)


#========================
#     ROUTES
#========================

@app.route('/')
def show_all():
    """
    Shows all assignments

    Parameters: None
    """
    users, dates = read_data()
    return serialize_data(users, dates)


@app.route('/users/<username>', methods=['GET', 'PUT', 'DELETE'])
def get_user_route(username):
    """
    Info per user
    GET: get the date assigned to user
    PUT: add a new user and assign a new date to him
    DELETE: remove a user from the data
    """
    global USERS
    global DATES
    if not USERS:
        USERS, DATES = read_data()
    if request.method == 'GET':
        if username not in USERS:
            abort(404)
        users, dates = get_user(username)
        return serialize_data(users, dates)
    elif request.method == 'DELETE':
        if username not in USERS:
            abort(404)
        delete_user(username)
        return '', 200
    elif request.method == 'PUT':
        if username in USERS:
            return 'User already in list', 204
        add_user(username)
        return serialize_data(USERS, DATES)


@app.route('/new', methods=['POST'])
def regenerate_route():
    """
    Start a new assignment series. The assignment will start on the next day
    with weekday = ASSIGNMENT_WEEKDAY_START and has an interval of
    ASSIGNMENT_INTERVAL_DAYS

    Parameters: None
    """
    global USERS
    global DATES
    if not USERS:
        USERS, DATES = read_data()
    regenerate(USERS)
    return serialize_data(USERS, DATES)


@app.route('/lookup', methods=['GET'])
def lookup_route():
    """
    Search who is assigned during a given period (for instance: next week)
    By default, the next assignment is returned.

    Parameters:
      - from: beginning of the period in which to search for assignments
      - to: end of the period in which to search for assignments
    """
    global USERS
    global DATES
    if not USERS:
        USERS, DATES = read_data()
    period_begin = request.args.get('from', default=datetime.date.today(), type=to_date)
    period_end = request.args.get('to', type=to_date)
    _users, _dates = lookup(period_begin, period_end)
    return serialize_data(_users, _dates)


@app.route('/delay', methods=['POST'])
def delay_route():
    """
    Delay one or several assignments.
    You can delay only the upcoming assignment by specifying all=false (default). In this
    case, it is not allowed to delay it beyond the next assignment.
    When all=true, the next assignment and all subsequent assignments will be
    delayed.

    Parameters:
      - days: number of days to delay the assignment. Limited if all=false
      - all: (true or false) whether to delay only the upcoming assignment (all=false)
             or also all subsequent assignments.
    """
    global USERS
    global DATES
    if not USERS:
        USERS, DATES = read_data()
    # TODO: this is now a POST request, should get the params from the data?
    delay_days = request.args.get('days', default=1, type=int)
    delay_all_str = request.args.get('all', 'false')
    delay_all = delay_all_str in ['true', 'True']
    delay(delay_all, delay_days)
    return serialize_data(USERS, DATES)


@app.route('/swap', methods=['POST'])
def swap_route():
    """
    Swap the dates of two users

    Parameters:
      - user: the username to swap. You MUST supply this parameter exactly 2 times.
    """
    global USERS
    global DATES
    if not USERS:
        USERS, DATES = read_data()
    swap_users = request.args.getlist('user')
    if len(swap_users) != 2:
        abort(400)
    swap(*swap_users)
    return serialize_data(USERS, DATES)


@app.route('/dialogflow', methods=['POST'])
def dialogflow():
    """
    Endpoint to be used by dialogflow

    Can only be called with a POST method, and the request
    body contains data as described here:
    https://cloud.google.com/dialogflow/docs/fulfillment-how#request_format
    """
    global USERS
    global DATES
    if not USERS:
        USERS, DATES = read_data()
    data = request.get_json()
    print(data)
    action = data['queryResult']['action']
    response = {'fulfillment_text': 'Sorry, that failed. Can you try again?'}
    if action == 'next':
        period_begin = datetime.date.today()
        users, dates = lookup(period_begin, None)
        response = {'fulfillment_text': f'The next person is {users[0]} ({dates[0]})'}
    elif action == 'get-assignments-for-period':
        period = data['queryResult']['parameters'].get('date-period')
        if period:
            start = datetime.datetime.fromisoformat(period['startDate']).date()
            end = datetime.datetime.fromisoformat(period['endDate']).date()
            users, dates = lookup(start, end)
            response = {
                'fulfillmentMessages': [{'text': {'text': [f'{users[i]}:\t{dates[i]}']}} for i in range(len(dates))]}
        else:
            abort(400)

    elif action == 'add':
        user = data['queryResult']['parameters'].get('person')
        if user:
            username = user['name']
            add_user(username)
            users, dates = get_user(username)
            response = {'fulfillment_text': f'I added {username}. He/she is scheduled for {dates[0]}.'}
        else:
            abort(400)
    elif action == 'show-all':
        users, dates = read_data()
        if len(users) > 0:
            response = {'fulfillmentMessages': [{'text': {'text': [f'{users[i]}:\t{dates[i]}']}} for i in range(len(dates))]}
        else:
            response = {'fulfillment_text': 'There are no users added yet.'}
    elif action == 'lookup-user':
        user = data['queryResult']['parameters'].get('person')
        if user:
            username = user['name']
            users, dates = get_user(username)
            response = {'fulfillment_text': f'{username} is scheduled for {dates[0]}.'}
        else:
            abort(400)
    elif action == 'remove':
        user = data['queryResult']['parameters'].get('person')
        if user:
            username = user['name']
            delete_user(username)
            response = {'fulfillment_text': f'Ok, I removed {username} from the list.'}
        else:
            abort(400)
    elif action == 'swap':
        user1 = data['queryResult']['parameters'].get('person')
        user2 = data['queryResult']['parameters'].get('other_person')
        if user1 and user2:
            username1 = user1['name']
            username2 = user2['name']
            swap(username1, username2)
            response = {'fulfillment_text': f'Ok, I swapped {username1} and {username2}.'}
        else:
            abort(400)
    elif action == 'delay-next':
        days = data['queryResult']['parameters'].get('duration')
        if days:
            delay(delay_all=False, delay_days=days)
            if days == 1:
                days_str = '1 day'
            else:
                days_str = f'{days} days'
            response = {'fulfillment_text': f'Ok, I delayed the next assignment with {days_str}.'}
        else:
            abort(400)
    elif action == 'delay-all':
        days = data['queryResult']['parameters'].get('duration')
        if days:
            delay(delay_all=True, delay_days=days)
            if days == 1:
                days_str = '1 day'
            else:
                days_str = f'{days} days'
            response = {'fulfillment_text': f'Ok, I delayed all assignments with {days_str}.'}
        else:
            abort(400)
    return response


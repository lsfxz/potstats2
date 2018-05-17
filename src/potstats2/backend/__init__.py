import configparser
import datetime
import functools
import hashlib
import json
import marshal

from flask import Flask, request, Response, url_for, g, Request
from sqlalchemy import func, desc
from sqlalchemy.dialects.postgresql import insert

from .. import db, dal, config
from ..db import Post, User, CachedAPIRequest

app = Flask(__name__)
no_default = object()

cfg = configparser.ConfigParser()
try:
    with open(config.INI_PATH, 'r') as fd:
        cfg.read_file(fd)
except FileNotFoundError:
    pass
try:
    app.config.from_mapping({k.upper(): v for k, v in cfg['flask'].items()})
except KeyError:
    pass


def get_session():
    try:
        return g.session
    except AttributeError:
        g.session = db.get_session()
        return g.session


@app.teardown_request
def close_db_session(exc):
    if hasattr(g, 'session'):
        g.session.close()


def cache_key(view, view_args, view_kwargs, request: Request):
    return hashlib.sha256(marshal.dumps({
        'view': view.__name__,
        'view_args': view_args,
        'view_kwargs': view_kwargs,
        'request_url': request.full_path,  # order controlled by UA, so possibly doubled cache entries
    })).digest()


def cache_api_view(view):
    @functools.wraps(view)
    def cache_frontend(*args, **kwargs):
        key = cache_key(view, args, kwargs, request)
        session = get_session()
        cached = session.query(CachedAPIRequest).get(key)
        if not cached:
            response = view(*args, **kwargs)
            if response.status_code == 200 and response.mimetype == 'application/json':
                stmt = insert(CachedAPIRequest.__table__).values(
                    key=key, data=response.get_data(as_text=False), timestamp=datetime.datetime.utcnow())
                stmt = stmt.on_conflict_do_nothing()
                session.rollback()
                session.execute(stmt)
                session.commit()
            return response
        else:
            print('From cache')
            return Response(cached.data, status=200, mimetype='application/json')
    return cache_frontend


class DatabaseAwareJsonEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, User):
            return {
                'name': o.name,
                'uid': o.uid,
            }
        if callable(getattr(o, 'to_json', None)):
            return o.to_json()
        return super().default(o)


def json_response(data, status_code=200):
    return Response(json.dumps(data, cls=DatabaseAwareJsonEncoder), status=status_code, mimetype='application/json')


class APIError(Exception):
    status_code = 400

    def __init__(self, message, status_code=None):
        super().__init__()
        self.message = str(message)
        self.status_code = status_code or type(self).status_code

    def get_response(self):
        return json_response({
            'error': self.message,
        }, status_code=self.status_code)


def request_arg(argument, type, default=no_default):
    try:
        return type(request.args[argument])
    except KeyError as exc:
        if default is not no_default:
            return default
        raise APIError('Missing request argument %s' % argument)
    except ValueError as exc:
        raise APIError('Malformed request argument %s: %s' % (argument, exc))


@app.errorhandler(APIError)
def handle_api_error(error: APIError):
    return error.get_response()


@app.route('/api/boards')
def boards():
    session = get_session()
    rows = {}
    for row in dal.boards(session).all():
        rows[row.Board.bid] = {
            'name': row.Board.name,
            'description': row.Board.description,
            'thread_count': row.thread_count,
            'post_count': int(row.post_count),
        }
    return json_response(rows)


@app.route('/api/social-graph')
def social_graph():
    session = get_session()
    limit = request_arg('limit', int, default=1000)
    rows = []
    query = dal.social_graph(session).limit(limit)
    for relation in query.all():
        rows.append({
            'from': relation.quoter,
            'to': relation.quotee,
            'count': relation.count,
            'intensity': relation.intensity,
        })
    return json_response({'rows': rows})


@app.route('/api/poster-stats')
@cache_api_view
def poster_stats():
    """
    Basic posting statistics on users

    Query parameters:
    - year: optional int, restrict to certain year
    - limit: optional int, default 1000, restrict number of rows
    - order_by: asc/desc, default desc, set sort direction
    - order_by_column: default post_count, one of ('post_count', 'edit_count', 'avg_post_length', 'threads_created')
    """
    session = get_session()

    year = request_arg('year', int, default=None)
    bid = request_arg('bid', int, default=None)
    limit = request_arg('limit', int, default=1000)
    order_by_order = request_arg('order_by', str, default='desc')
    order_by_column = request_arg('order_by_column', str, default='post_count')

    if order_by_column not in ('post_count', 'edit_count', 'avg_post_length', 'threads_created'):
        raise APIError('Invalid order_by_column: %s' % order_by_column)

    try:
        order_by = {
            'asc': order_by_column,
            'desc': desc(order_by_column),
        }[order_by_order]
    except KeyError:
        raise APIError('Invalid order_by: %s' % order_by_order)

    query = dal.poster_stats(session, year, bid).order_by(order_by).limit(limit)

    rows = []
    for r in query.all():
        rows.append({
            'user': {'name': r.User.name, 'uid': r.User.uid},
            'post_count': r.post_count,
            'edit_count': r.edit_count,
            'avg_post_length': r.avg_post_length,
            'threads_created': r.threads_created
        })

    return json_response({'rows': rows})


def time_segregated_stats(time_column, time_column_name):
    def view():
        session = get_session()
        year = request_arg('year', int, default=None)
        bid = request_arg('bid', int, default=None)

        query = dal.aggregate_stats_segregated_by_time(session, time_column, year, bid)

        rows = {}
        for row in query.all():
            row = row._asdict()
            rows[row.pop('time')] = row

        return json_response({'rows': rows})
    view.__name__ = 'view_' + time_column_name
    return view


app.route('/api/weekday-stats')(
    time_segregated_stats(func.to_char(Post.timestamp, 'ID'), 'weekday')
)

app.route('/api/hourly-stats')(
    time_segregated_stats(func.to_char(Post.timestamp, 'WW:ID:HH24'), 'weekday_hour')
)

app.route('/api/year-over-year-stats')(
    time_segregated_stats(func.extract('year', Post.timestamp), 'year')
)


@app.route('/api/')
def api():
    apis = []
    for rule in app.url_map.iter_rules():
        if rule.rule.startswith('/api') and rule.endpoint != 'api':
            apis.append(url_for(rule.endpoint, _external=True))
    return json_response({'apis': apis})


def main():
    print('Only for development!')
    app.run()

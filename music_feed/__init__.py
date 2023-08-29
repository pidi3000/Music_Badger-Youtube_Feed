"""
App factory init
"""

import os

from flask import Flask, render_template, Response, url_for, redirect

from ._data.config import Config
from .extension import db


def _register_all_blueprints(app: Flask):
    from . import youtube
    youtube.init(app)

    from . import feed
    feed.init(app)

    from . import channel
    channel.init(app)

    from . import tag
    tag.init(app)


def _register_base_routes(app: Flask):
    base_template_dir = os.path.abspath(os.path.dirname(__file__))
    # db_path = os.path.join(base_template_dir, 'database.db')
    # print(base_template_dir)
    # print(os.path.join(base_template_dir, "templates/stylesheets/{}.css".format("stylesheetName")))

    def _get_absolute_path(relative_path):
        # return None
        return os.path.join(base_template_dir, relative_path)

    @app.route('/')
    def index():
        return redirect(url_for('subfeed.index'))

    @app.route("/style/<stylesheetName>.css")
    def returnStyle(stylesheetName):

        print(stylesheetName)

        with open(_get_absolute_path("templates/stylesheets/{}.css".format(stylesheetName)), "r", encoding="utf-8") as file:
            stylesheet = file.read()

        return Response(stylesheet, mimetype="text/css")

    @app.route("/scripts/<scriptName>.js")
    def return_Script(scriptName):

        print(scriptName)

        with open(_get_absolute_path("templates/scripts/{}.js".format(scriptName)), "r", encoding="utf-8") as file:
            stylesheet = file.read()

        return Response(stylesheet, mimetype="application/javascript")

    @app.route('/test/')
    def test_page():
        return '<h1>Testing the Flask Application Factory Pattern</h1>'


def _init_db(app: Flask):
    db.init_app(app)

    from . import db_models
    with app.app_context():
        db.create_all()


def init_with_app(app:Flask):
    print(Config.SQLALCHEMY_DATABASE_URI)
    _init_db(app)
    _register_all_blueprints(app)
    _register_base_routes(app)


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    init_with_app(app)

    return app
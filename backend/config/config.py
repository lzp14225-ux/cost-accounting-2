#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
账号侧兼容配置。
统一从 shared.config/.env 读取运行时配置，避免在旧模块里继续写死地址、端口和密钥。
"""

import os
from dotenv import load_dotenv

from shared.config import settings

load_dotenv()


class Config:
    APP_NAME = settings.APP_NAME
    APP_VERSION = settings.APP_VERSION
    DEBUG = settings.DEBUG
    HOST = settings.SERVER_HOST
    PORT = settings.UNIFIED_PORT

    DB_HOST = settings.DB_HOST
    DB_PORT = settings.DB_PORT
    DB_NAME = settings.DB_NAME
    DB_USER = settings.DB_USER
    DB_PASSWORD = settings.DB_PASSWORD

    DB_POOL_SIZE = 5
    DB_MAX_OVERFLOW = 10
    DB_POOL_TIMEOUT = 30

    JWT_SECRET_KEY = settings.JWT_SECRET_KEY
    JWT_ALGORITHM = settings.JWT_ALGORITHM
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES = settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES

    MAX_FAILED_LOGIN_ATTEMPTS = int(os.getenv("MAX_FAILED_ATTEMPTS", 5))
    PASSWORD_HASH_ROUNDS = int(os.getenv("BCRYPT_ROUNDS", 12))

    LOG_LEVEL = settings.LOG_LEVEL
    LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    @classmethod
    def get_database_url(cls):
        return f"postgresql://{cls.DB_USER}:{cls.DB_PASSWORD}@{cls.DB_HOST}:{cls.DB_PORT}/{cls.DB_NAME}"

    @classmethod
    def get_database_config(cls):
        return {
            "host": cls.DB_HOST,
            "port": cls.DB_PORT,
            "database": cls.DB_NAME,
            "user": cls.DB_USER,
            "password": cls.DB_PASSWORD,
        }


class DevelopmentConfig(Config):
    DEBUG = True
    LOG_LEVEL = "DEBUG"


class ProductionConfig(Config):
    DEBUG = False
    LOG_LEVEL = "WARNING"
    MAX_FAILED_LOGIN_ATTEMPTS = 3
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES = 15


class TestingConfig(Config):
    DEBUG = True
    DB_NAME = "test_mold_cost_db"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES = 5


config_map = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
    "default": DevelopmentConfig,
}


def get_config(config_name=None):
    if config_name is None:
        config_name = os.getenv("FLASK_ENV", "default")
    return config_map.get(config_name, DevelopmentConfig)

from models.user_setting import UserSetting


class SQLAlchemySettingsRepository:
    def __init__(self, db):
        self.db = db

    def get(self, key, default=None):
        row = self.db.query(UserSetting).filter(UserSetting.key == key).first()
        return row.value if row else default

    def set(self, key, value):
        row = self.db.query(UserSetting).filter(UserSetting.key == key).first()
        if row:
            row.value = value
        else:
            row = UserSetting(key=key, value=value)
            self.db.add(row)
        self.db.commit()
        return row.value

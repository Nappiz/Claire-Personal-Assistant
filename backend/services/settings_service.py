from sqlalchemy.orm import Session
from models.user_setting import UserSetting

def get_setting(db: Session, key: str, default_value=None):
    setting = db.query(UserSetting).filter(UserSetting.key == key).first()
    if setting:
        return setting.value
    return default_value

def set_setting(db: Session, key: str, value):
    setting = db.query(UserSetting).filter(UserSetting.key == key).first()
    if setting:
        setting.value = value
    else:
        setting = UserSetting(key=key, value=value)
        db.add(setting)
    db.commit()
    return setting.value

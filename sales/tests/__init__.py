from django.test.utils import override_settings

# 測試只需密碼可驗證；正式等級 PBKDF2 每次約 0.4 秒，會讓建立使用者的測試慢數倍。
# 放在測試套件內而非 settings.py，正式環境與版號判定都不受影響。
override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"]).enable()

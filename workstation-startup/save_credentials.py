
import keyring
import getpass

SERVICE = "CampusNetwork"

username = input("请输入校园网账号：").strip()
password = getpass.getpass("请输入校园网密码：")

if not username or not password:
    print("账号或密码不能为空")
else:
    keyring.set_password(SERVICE, "username", username)
    keyring.set_password(SERVICE, "password", password)
    print("校园网凭据已保存到 Windows 凭据存储。")

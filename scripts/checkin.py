import os
import json
import time
import random
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ================== 配置 ==================
LOGIN_URL = "https://mufyai.com/api/users/login"
PROFILE_URL = "https://mufyai.com/api/users/profiles"

TIMEOUT = 10
RETRY = 3
DELAY_RANGE = (3, 8)

# ================== 工具函数 ==================
def log(msg: str):
    print(time.strftime("[%Y-%m-%d %H:%M:%S]"), msg, flush=True)

def send_email(subject: str, content: str):
    smtp_server = os.getenv("SMTP_SERVER")
    smtp_port = int(os.getenv("SMTP_PORT", "465"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    mail_to = os.getenv("MAIL_TO")

    if not all([smtp_server, smtp_user, smtp_pass, mail_to]):
        log("⚠️ 邮件配置不完整，跳过邮件通知")
        return

    msg = MIMEMultipart()
    msg["From"] = smtp_user
    msg["To"] = mail_to
    msg["Subject"] = subject
    msg.attach(MIMEText(content, "plain", "utf-8"))

    try:
        with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        log("📧 邮件发送成功")
    except Exception as e:
        log(f"❌ 邮件发送失败: {e}")

# ================== 核心逻辑 ==================
def process_account(email: str, password: str):
    session = requests.Session()

    # ---------- 登录（即签到）----------
    for attempt in range(1, RETRY + 1):
        try:
            r = session.post(
                LOGIN_URL,
                json={"email": email, "password": password},
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "Mozilla/5.0"
                },
                timeout=TIMEOUT
            )

            if r.status_code != 200:
                raise Exception(f"HTTP {r.status_code}")

            result = r.json()
            if result.get("code") != 200:
                return {
                    "email": email,
                    "username": None,
                    "status": "failed",
                    "reason": result.get("reason", "登录失败")
                }

            data = result["data"]
            token = data["token"]
            user_id = data.get("userId")
            break

        except Exception as e:
            if attempt == RETRY:
                return {
                    "email": email,
                    "username": None,
                    "status": "failed",
                    "reason": str(e)
                }
            time.sleep(2)

    # ---------- 获取用户信息 ----------
    try:
        r = session.get(
            PROFILE_URL,
            params={"userId": user_id},
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": "Mozilla/5.0"
            },
            timeout=TIMEOUT
        )

        if r.status_code != 200:
            raise Exception(f"profile HTTP {r.status_code}")

        result = r.json()
        if result.get("code") != 200:
            raise Exception(result.get("reason"))

        username = result["data"].get("username")

        return {
            "email": email,
            "username": username,
            "status": "success",
            "reason": None
        }

    except Exception as e:
        return {
            "email": email,
            "username": None,
            "status": "failed",
            "reason": str(e)
        }

# ================== 主程序 ==================
def main():
    accounts = json.loads(os.getenv("ACCOUNTS", "[]"))

    if not accounts:
        log("❌ 未配置 ACCOUNTS")
        return

    results = []

    for idx, acc in enumerate(accounts, 1):
        email = acc["email"]
        password = acc["password"]

        log(f"[{idx}/{len(accounts)}] 处理账号：{email}")
        result = process_account(email, password)
        results.append(result)

        log(f"结果：{result['status']} "
            f"{result['username'] or ''} "
            f"{result['reason'] or ''}")

        time.sleep(random.randint(*DELAY_RANGE))

    # ---------- 汇总 ----------
    success = [r for r in results if r["status"] == "success"]
    failed = [r for r in results if r["status"] == "failed"]

    log("========== 汇总 ==========")
    log(f"✅ 成功：{len(success)}")
    for r in success:
        log(f"  - {r['username']} ({r['email']})")

    log(f"❌ 失败：{len(failed)}")
    for r in failed:
        log(f"  - {r['email']}：{r['reason']}")

    # ---------- 邮件 ----------
    lines = []
    lines.append("自动登录 / 签到结果汇总\n")

    lines.append(f"成功：{len(success)}")
    for r in success:
        lines.append(f"  - {r['username']} ({r['email']})")

    lines.append("")
    lines.append(f"失败：{len(failed)}")
    for r in failed:
        lines.append(f"  - {r['email']}：{r['reason']}")

    mail_content = "\n".join(lines)

    if failed:
        send_email("❌ 自动签到存在失败账号", mail_content)
    else:
        send_email("✅ 自动签到全部成功", mail_content)

if __name__ == "__main__":
    main()

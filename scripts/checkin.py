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
CHECKIN_URL = "https://mufyai.com/api/users/checkin"

TIMEOUT = 10
DELAY_RANGE = (5, 15)  # 每个账号间延迟

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
        log(f"❌ 邮件发送失败: {str(e)}")

def send_wechat(title: str, content: str):
    wx_url = os.getenv("WX_PUSH_URL")
    wx_token = os.getenv("WX_PUSH_TOKEN")

    if not wx_url or not wx_token:
        log("⚠️ 未配置微信推送，跳过微信通知")
        return

    try:
        r = requests.post(
            wx_url,
            headers={
                "Authorization": wx_token,
                "Content-Type": "application/json"
            },
            json={
                "title": title,
                "content": content
            },
            timeout=10
        )

        if r.status_code == 200:
            log("📲 微信推送成功")
        else:
            log(f"❌ 微信推送失败 HTTP {r.status_code}: {r.text}")
    except Exception as e:
        log(f"❌ 微信推送异常: {str(e)}")

def build_wechat_message(results):
    success = [r for r in results if r["status"] == "success"]
    failed = [r for r in results if r["status"] == "failed"]

    lines = []
    lines.append("📅 自动签到报告")
    lines.append("━━━━━━━━━━━━━━")
    lines.append(f"⏰ 时间：{time.strftime('%Y-%m-%d %H:%M')}")
    lines.append("")
    lines.append(f"✅ 成功（{len(success)}）")
    for r in success:
        lines.append(f"• {r['username']}：{r['reason']}")

    if failed:
        lines.append("")
        lines.append(f"❌ 失败（{len(failed)}）")
        for r in failed:
            lines.append(f"• {r['username']}：{r['reason']}")

    lines.append("━━━━━━━━━━━━━━")
    return "\n".join(lines)

# ================== 核心功能 ==================
def do_checkin(session, token):
    try:
        r = session.post(
            CHECKIN_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": "Mozilla/5.0"
            },
            timeout=TIMEOUT
        )

        if r.status_code == 200:
            result = r.json()
            if result.get("code") == 200:
                return True, "签到成功"
            reason = result.get("reason", "")
            if "已" in reason:
                return True, "今日已签到"
            return False, reason or "签到失败"

        elif r.status_code == 429:
            return False, "HTTP 429（请求过多）"
        elif r.status_code >= 500:
            return False, f"HTTP {r.status_code}（服务器错误）"
        else:
            return False, f"HTTP {r.status_code}"

    except Exception as e:
        return False, str(e)

def process_account(email: str, password: str):
    session = requests.Session()
    username = email

    # ---------- 登录 ----------
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

        r.raise_for_status()
        result = r.json()

        if result.get("code") != 200:
            return {"email": email, "username": email, "status": "failed", "reason": result.get("reason", "登录失败")}

        data = result["data"]
        token = data["token"]
        user_id = data.get("userId")

    except Exception as e:
        return {"email": email, "username": email, "status": "failed", "reason": str(e)}

    # ---------- 获取用户名 ----------
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
        if r.status_code == 200:
            result = r.json()
            if result.get("code") == 200:
                username = result["data"].get("username") or email
    except:
        pass

    # ---------- 签到 ----------
    ok, msg = do_checkin(session, token)

    return {
        "email": email,
        "username": username,
        "status": "success" if ok else "failed",
        "reason": msg
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

        icon = "✅" if result["status"] == "success" else "❌"
        log(f"{icon} {result['username']}：{result['reason']}")

        time.sleep(random.randint(*DELAY_RANGE))

    # ---------- 汇总 ----------
    success = [r for r in results if r["status"] == "success"]
    failed = [r for r in results if r["status"] == "failed"]

    mail_lines = []
    mail_lines.append("自动签到结果汇总\n")
    mail_lines.append(f"成功：{len(success)}")
    for r in success:
        mail_lines.append(f"  - {r['username']}：{r['reason']}")
    mail_lines.append("")
    mail_lines.append(f"失败：{len(failed)}")
    for r in failed:
        mail_lines.append(f"  - {r['username']}：{r['reason']}")

    mail_content = "\n".join(mail_lines)

    log("========== 汇总 ==========")
    log(mail_content)

    # 邮件
    subject = "❌ 自动签到存在失败账号" if failed else "✅ 自动签到全部成功"
    send_email(subject, mail_content)

    # 微信
    wx_title = f"签到完成｜成功 {len(success)} / 失败 {len(failed)}"
    wx_content = build_wechat_message(results)
    send_wechat(wx_title, wx_content)

if __name__ == "__main__":
    main()

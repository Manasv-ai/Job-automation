import requests


def send_telegram_alert(bot_token: str, chat_id: str, job_info: dict) -> bool:
    score_pct = int(float(job_info.get("match_score", 0.8)) * 100)
    message = (
        f"High-match job ({score_pct}%)\n\n"
        f"Role: {job_info.get('title', 'N/A')}\n"
        f"Company: {job_info.get('company', 'N/A')}\n"
        f"Location: {job_info.get('location', 'N/A')}\n"
        f"Board: {str(job_info.get('site', 'N/A')).title()}\n"
        f"Skills: {job_info.get('key_matches', 'N/A')}\n\n"
        f"Apply: {job_info.get('job_url')}"
    )
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "disable_web_page_preview": False,
    }
    try:
        resp = requests.post(url, json=payload, timeout=12)
        return resp.ok
    except requests.RequestException as exc:
        print(f"[Notifier Error] {exc}")
        return False

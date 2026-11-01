from __future__ import annotations

import logging

import requests

log = logging.getLogger("agent.notify")


def send_text(text: str) -> bool:
    """Telegram alert using the existing config.json / env credentials. Never raises."""
    try:
        from config_loader import load_config

        cfg = load_config()
        token = (cfg.get("telegram_bot_token") or "").strip()
        chat = (cfg.get("telegram_chat_id") or "").strip()
        if not token or not chat or "YOUR_TELEGRAM" in token.upper():
            return False
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": text[:3900], "disable_web_page_preview": True},
            timeout=12,
        )
        return r.ok
    except Exception as e:  # noqa: BLE001
        log.warning("telegram failed: %s", e)
        return False

import base64
import logging
import time

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

TOSS_CONFIRM_URL = "https://api.tosspayments.com/v1/payments/confirm"
TOSS_CANCEL_URL = "https://api.tosspayments.com/v1/payments/{payment_key}/cancel"


class TossPaymentsService:
    MAX_RETRIES = 3
    RETRY_DELAY = 1  # seconds

    @staticmethod
    def _get_auth_header():
        secret = settings.TOSS_SECRET_KEY
        encoded = base64.b64encode(f"{secret}:".encode()).decode()
        return {"Authorization": f"Basic {encoded}", "Content-Type": "application/json"}

    @classmethod
    def _request_with_retry(cls, method: str, url: str, **kwargs) -> requests.Response:
        """재시도 로직이 포함된 HTTP 요청"""
        headers = cls._get_auth_header()
        last_exception = None

        for attempt in range(1, cls.MAX_RETRIES + 1):
            try:
                response = requests.request(
                    method, url, headers=headers, timeout=30, **kwargs
                )

                # 4xx 에러는 재시도하지 않음 (클라이언트 에러)
                if 400 <= response.status_code < 500:
                    return response

                # 5xx 에러는 재시도
                if response.status_code >= 500:
                    logger.warning(
                        "TossPayments %s %s: %d (attempt %d/%d)",
                        method, url, response.status_code, attempt, cls.MAX_RETRIES,
                    )
                    if attempt < cls.MAX_RETRIES:
                        time.sleep(cls.RETRY_DELAY * attempt)
                        continue

                return response

            except requests.exceptions.Timeout:
                logger.warning(
                    "TossPayments timeout: %s (attempt %d/%d)",
                    url, attempt, cls.MAX_RETRIES,
                )
                last_exception = "timeout"
                if attempt < cls.MAX_RETRIES:
                    time.sleep(cls.RETRY_DELAY * attempt)

            except requests.exceptions.ConnectionError:
                logger.warning(
                    "TossPayments connection error: %s (attempt %d/%d)",
                    url, attempt, cls.MAX_RETRIES,
                )
                last_exception = "connection_error"
                if attempt < cls.MAX_RETRIES:
                    time.sleep(cls.RETRY_DELAY * attempt)

        return None

    @classmethod
    def confirm_payment(cls, payment_key: str, order_id: str, amount: int) -> dict:
        """토스페이먼츠 결제 승인 API 호출 (재시도 포함)"""
        payload = {
            "paymentKey": payment_key,
            "orderId": order_id,
            "amount": amount,
        }

        response = cls._request_with_retry("POST", TOSS_CONFIRM_URL, json=payload)

        if response is None:
            logger.error("TossPayments confirm failed after %d retries", cls.MAX_RETRIES)
            return {"success": False, "error": {"code": "NETWORK_ERROR", "message": "결제 승인 요청 실패"}}

        if response.status_code == 200:
            return {"success": True, "data": response.json()}

        logger.error("TossPayments confirm failed: %s", response.text)
        return {"success": False, "error": response.json()}

    @classmethod
    def cancel_payment(cls, payment_key: str, cancel_reason: str) -> dict:
        """토스페이먼츠 결제 취소 API 호출"""
        url = TOSS_CANCEL_URL.format(payment_key=payment_key)
        payload = {"cancelReason": cancel_reason}

        response = cls._request_with_retry("POST", url, json=payload)

        if response is None:
            return {"success": False, "error": {"code": "NETWORK_ERROR", "message": "결제 취소 요청 실패"}}

        if response.status_code == 200:
            return {"success": True, "data": response.json()}

        logger.error("TossPayments cancel failed: %s", response.text)
        return {"success": False, "error": response.json()}

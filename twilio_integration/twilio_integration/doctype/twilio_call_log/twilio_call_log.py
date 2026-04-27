import json
from urllib.parse import parse_qs, urlparse, urlunparse

import frappe
from frappe.model.document import Document
from frappe.utils import add_to_date, get_url, money_in_words, now_datetime
from twilio.rest import Client
from werkzeug.wrappers import Response

# -------------------------------------------------------------------
# DocType Logic
# -------------------------------------------------------------------


class TwilioCallLog(Document):
    def before_insert(self):
        if not self.timestamp:
            self.timestamp = now_datetime()

        try:
            set_call_data(self)
        except Exception:
            frappe.log_error(
                frappe.get_traceback(), "Twilio Call Log: before_insert failed"
            )


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------


def force_https(url: str) -> str:
    """Convert URL to HTTPS (required by Twilio for callbacks)"""
    parsed = urlparse(url)

    # If scheme is missing, assume http first
    scheme = "https"

    return urlunparse(
        (
            scheme,
            parsed.netloc or parsed.path,  # handles urls without scheme
            parsed.path if parsed.netloc else "",
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


def _get_value(data, key):
    """Extract value from dict, handling both single values and lists"""
    value = data.get(key)
    if isinstance(value, list):
        return value[0]
    return value


def set_call_data(doc):
    """Parse call data from response JSON and populate document fields"""
    if not doc.response:
        return

    data = json.loads(doc.response)

    call_sid = _get_value(data, "CallSid")
    call_status = _get_value(data, "CallStatus")
    duration = _get_value(data, "Duration")
    call_duration = _get_value(data, "CallDuration")
    from_no = _get_value(data, "From")
    to_no = _get_value(data, "To")

    if call_sid and not doc.call_sid:
        doc.call_sid = call_sid

    if call_status:
        doc.call_status = call_status

    if duration:
        try:
            doc.duration = int(duration)
        except Exception:
            pass

    # Also capture total call duration if available
    if call_duration:
        try:
            doc.call_duration = int(call_duration)
        except Exception:
            pass

    if from_no:
        doc.from_no = from_no

    if to_no:
        doc.to_no = to_no

    if not call_sid:
        return

    # Find parent Call log and mark it as callback received
    parent = frappe.db.exists(
        "Twilio Call Log",
        {"call_sid": call_sid, "type": "Call", "call_back_recieved": 0},
    )

    if parent:
        frappe.db.set_value("Twilio Call Log", parent, "call_back_recieved", 1)


# -------------------------------------------------------------------
# Generic Call Initiator
# -------------------------------------------------------------------


@frappe.whitelist()
def initiate_twilio_call(
    to_number,
    twiml_url,
    purpose,
    reference_doctype=None,
    reference_name=None,
    meta=None,
):
    """
    Initiate a Twilio call with automatic retry capability.

    Args:
            to_number: Phone number to call
            twiml_url: URL containing TwiML instructions
            purpose: Purpose/reason for the call
            reference_doctype: Optional link to another doctype
            reference_name: Optional link to another document
            meta: Optional metadata dict

    Returns:
            dict: {log: log_name, call_sid: twilio_call_sid}
    """
    if "twilio_integration" not in frappe.get_installed_apps():
        frappe.throw("Twilio integration not installed")

    from twilio_integration.twilio_integration.twilio_handler import Twilio

    twilio = Twilio.connect()
    if not twilio:
        frappe.throw("Twilio not configured")

    settings = frappe.get_single("Twilio Settings")

    # Validate settings
    if settings.enable_recurring_call:
        if not settings.no_of_recurring_call:
            frappe.throw(
                "Please configure 'Number of Recurring Calls' in Twilio Settings"
            )

        if not settings.recurring_call_buffer_time:
            frappe.throw(
                "Please configure 'Recurring Call Buffer Time' in Twilio Settings"
            )

    from_number = twilio.settings.whatsapp_no

    # Validate phone numbers
    if not to_number:
        frappe.throw("To number is required")

    if not from_number:
        frappe.throw("From number not configured in Twilio Settings")

    status_callback_url = get_url() + "/api/method/twilio_call_log_endpoint"
    https_status_callback_url = force_https(status_callback_url)

    log = frappe.get_doc(
        {
            "doctype": "Twilio Call Log",
            "type": "Call",
            "purpose": purpose,
            "to_no": to_number,
            "from_no": from_number,
            "attempt_no": 1,
            "buffer_time": settings.recurring_call_buffer_time,
            "reference_doctype": reference_doctype,
            "reference_name": reference_name,
            "response": json.dumps(
                {
                    "twiml_url": twiml_url,
                    "callback_url": https_status_callback_url,
                    "meta": meta or {},
                }
            ),
        }
    )
    log.insert(ignore_permissions=True)

    client = Client(
        twilio.account_sid,
        twilio.settings.get_password("auth_token"),
    )

    try:
        call = client.calls.create(
            to=to_number,
            from_=from_number,
            url=twiml_url,
            record=False,
            status_callback=https_status_callback_url,
            status_callback_event=["completed"],
        )

        log.db_set("call_sid", call.sid)

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Twilio Call Initiation Failed")
        # Mark log as failed
        log.db_set("call_status", "failed")
        raise

    return {
        "log": log.name,
        "call_sid": call.sid,
    }


# -------------------------------------------------------------------
# Retry Executor (called by scheduler via enqueue)
# -------------------------------------------------------------------


def retry_twilio_call(log_name):
    """
    Retry a failed Twilio call.
    Called by scheduler when next_retry_at time is reached.
    """
    try:
        log = frappe.get_doc("Twilio Call Log", log_name)
    except Exception:
        frappe.log_error(
            frappe.get_traceback(), f"Failed to fetch Twilio Call Log: {log_name}"
        )
        return

    # Don't retry if call already completed
    if log.call_status == "completed":
        return

    # Don't retry if max attempts reached
    max_attempts = (
        frappe.db.get_single_value("Twilio Settings", "no_of_recurring_call") or 0
    )
    if log.attempt_no >= max_attempts:
        frappe.db.set_value(
            "Twilio Call Log", log_name, "call_status", "max_attempts_reached"
        )
        return

    # Clear retry marker so it doesn't loop
    log.db_set("next_retry_at", None)

    from twilio_integration.twilio_integration.twilio_handler import Twilio

    twilio = Twilio.connect()
    if not twilio:
        frappe.log_error("Twilio connection failed during retry")
        return

    client = Client(
        twilio.account_sid,
        twilio.settings.get_password("auth_token"),
    )

    status_callback_url = force_https(
        get_url() + "/api/method/twilio_call_log_endpoint"
    )

    response_data = json.loads(log.response)
    twiml_url = response_data.get("twiml_url")

    if not twiml_url:
        frappe.log_error(
            f"TwiML URL not found in response for log {log_name}", "Twilio Retry Failed"
        )
        return

    try:
        call = client.calls.create(
            to=log.to_no,
            from_=log.from_no,
            url=twiml_url,
            record=False,
            status_callback=status_callback_url,
            status_callback_event=["completed"],
        )

        log.db_set(
            {
                "call_sid": call.sid,
                "attempt_no": log.attempt_no + 1,
                "call_status": None,  # Reset status for new attempt
                "call_back_recieved": 0,  # Reset callback flag
            }
        )

    except Exception:
        frappe.log_error(
            frappe.get_traceback(), f"Twilio Call Retry Failed for {log_name}"
        )


def normalize_mobile_no(mobile_no, default_code="+91"):
    if not mobile_no:
        return None

    mobile_no = mobile_no.strip()

    if mobile_no.startswith("+"):
        return mobile_no

    return f"{default_code}{mobile_no}"


# -------------------------------------------------------------------
# Scheduler Processor (runs every minute)
# -------------------------------------------------------------------


def process_pending_retries():
    """
    Process all calls that are due for retry.
    This function is called by Frappe scheduler every minute.
    """
    now = now_datetime()

    logs = frappe.get_all(
        "Twilio Call Log",
        filters={
            "type": "Call",
            "call_status": ["!=", "completed"],
            "next_retry_at": ["<=", now],
        },
        fields=["name"],
    )

    for row in logs:
        frappe.enqueue(
            method="twilio_integration.twilio_integration.doctype.twilio_call_log.twilio_call_log.retry_twilio_call",
            queue="long",
            log_name=row.name,
            is_async=True,
        )


# -------------------------------------------------------------------
# Callback Webhook (receives status updates from Twilio)
# -------------------------------------------------------------------


@frappe.whitelist(allow_guest=True)
def twilio_call_log_endpoint():
    """
    Webhook endpoint for Twilio call status callbacks.
    This receives updates when calls complete, fail, etc.
    """
    raw_data = frappe.request.get_data(as_text=True)
    content_type = frappe.request.headers.get("Content-Type", "")

    if not raw_data:
        frappe.log_error("Empty webhook data received", "Twilio Callback")
        return

    try:
        # Parse webhook payload
        if "application/json" in content_type:
            payload = json.loads(raw_data)
        else:
            # Twilio typically sends application/x-www-form-urlencoded
            payload = parse_qs(raw_data)

        # Create callback log for audit trail
        doc = frappe.get_doc(
            {
                "doctype": "Twilio Call Log",
                "type": "Callback",
                "response": json.dumps(payload),
            }
        )
        doc.insert(ignore_permissions=True)

        # Extract call details
        call_sid = _get_value(payload, "CallSid")
        call_status = _get_value(payload, "CallStatus")

        if not call_sid:
            frappe.log_error(
                f"CallSid not found in payload: {payload}",
                "Twilio Callback Missing CallSid",
            )
            return

        # Find the parent Call log
        parent = frappe.db.exists(
            "Twilio Call Log",
            {"call_sid": call_sid, "type": "Call"},
        )

        if not parent:
            frappe.log_error(
                f"Parent Call log not found for CallSid: {call_sid}",
                "Twilio Callback Orphan",
            )
            return

        # Update parent log with callback status
        update_data = {
            "call_back_recieved": 1,
        }

        # Update call_status on parent log
        if call_status:
            update_data["call_status"] = call_status

        frappe.db.set_value("Twilio Call Log", parent, update_data)

        # Schedule retry if call failed and attempts remaining
        if call_status and call_status != "completed":
            log = frappe.get_doc("Twilio Call Log", parent)
            settings = frappe.get_single("Twilio Settings")
            max_attempts = settings.no_of_recurring_call or 0

            # Check if retries are possible
            if log.attempt_no < max_attempts:
                next_retry_time = add_to_date(
                    now_datetime(),
                    minutes=int(log.buffer_time) if log.buffer_time else 5,
                )

                frappe.db.set_value(
                    "Twilio Call Log", parent, "next_retry_at", next_retry_time
                )

                frappe.log_error(
                    f"Call {call_sid} status: {call_status}. Retry scheduled at {next_retry_time}",
                    "Twilio Call Retry Scheduled",
                )
            else:
                frappe.db.set_value(
                    "Twilio Call Log", parent, "call_status", "max_attempts_reached"
                )

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Twilio Callback Failure")

    finally:
        frappe.db.commit()


@frappe.whitelist(allow_guest=True)
def wallet_low_balance_url():
    params = frappe.request.args
    customer = params.get("customer")
    wallet_type = params.get("wallet_type")
    current_balance = params.get("current_balance")
    response = f"""<?xml version="1.0" encoding="UTF-8"?>
	<Response>
	<Say>Dear {customer}, Greeting from Liquiconnect Team!</Say>
	<Say>Your {wallet_type} wallet is having lower balance.</Say>
	<Say>Available wallet balance ({wallet_type}) : {money_in_words(current_balance)}</Say>
	<Say>Thanks, Liquiconnect Team.</Say>
	</Response>"""
    return Response(response, mimetype="text/xml")


@frappe.whitelist(allow_guest=True)
def fuel_theft_alert_url():
    params = frappe.request.args

    vehicle_no = params.get("vehicle_no")
    fuel_lost = params.get("fuel_lost")

    response = f"""<?xml version="1.0" encoding="UTF-8"?>
    <Response>
        <Say>Greetings from Liquiconnect Team.</Say>
        <Say>Fuel theft has been detected.</Say>
        <Say>Vehicle number {vehicle_no}.</Say>
        <Say>Approximate fuel loss is {fuel_lost} litres.</Say>
        <Say>Please take immediate action.</Say>
        <Say>Thank you. Liquiconnect Team.</Say>
    </Response>"""

    return Response(response, mimetype="text/xml")


@frappe.whitelist(allow_guest=True)
def vehicle_critical_dtc_alert_url():
    params = frappe.request.args

    vehicle_no = params.get("vehicle_no")
    dtc_code = params.get("dtc_code")
    dtc_description = params.get("dtc_description")

    response = f"""<?xml version="1.0" encoding="UTF-8"?>
    <Response>
        <Say>Greetings from Liquiconnect Team.</Say>
        <Say>Critical vehicle fault detected.</Say>
        <Say>Vehicle number {vehicle_no} has reported a critical DTC error.</Say>
        <Say>Error code {dtc_code}. {dtc_description}.</Say>
        <Say>Please Take necessary Action immediately.</Say>
        <Say>Thank you, Liquiconnect Team.</Say>
    </Response>"""

    return Response(response, mimetype="text/xml")

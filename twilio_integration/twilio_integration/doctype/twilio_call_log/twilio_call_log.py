import json
from urllib.parse import parse_qs

import frappe
from frappe.model.document import Document
from frappe.utils import (
	now_datetime,
	get_url,
	add_to_date,
)
from twilio.rest import Client
from urllib.parse import urlparse, urlunparse


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
				frappe.get_traceback(),
				"Twilio Call Log: before_insert failed"
			)


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------


def force_https(url: str) -> str:
    parsed = urlparse(url)

    # If scheme is missing, assume http first
    scheme = "https"

    return urlunparse((
        scheme,
        parsed.netloc or parsed.path,  # handles urls without scheme
        parsed.path if parsed.netloc else "",
        parsed.params,
        parsed.query,
        parsed.fragment
    ))



def _get_value(data, key):
	value = data.get(key)
	if isinstance(value, list):
		return value[0]
	return value


def set_call_data(doc):
	if not doc.response:
		return

	data = json.loads(doc.response)

	call_sid = _get_value(data, "CallSid")
	call_status = _get_value(data, "CallStatus")
	duration = _get_value(data, "Duration")
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

	if from_no:
		doc.from_no = from_no

	if to_no:
		doc.to_no = to_no

	if not call_sid:
		return

	parent = frappe.db.exists(
		"Twilio Call Log",
		{"call_sid": call_sid, "type": "Call","call_back_recieved":0}
	)

	if parent:
		frappe.db.set_value(
			"Twilio Call Log",
			parent,
			"call_back_recieved",
			1
		)


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
	if "twilio_integration" not in frappe.get_installed_apps():
		frappe.throw("Twilio integration not installed")

	from twilio_integration.twilio_integration.twilio_handler import Twilio

	twilio = Twilio.connect()
	if not twilio:
		frappe.throw("Twilio not configured")

	settings = frappe.get_single("Twilio Settings")

	from_number = twilio.settings.whatsapp_no

	status_callback_url = (
		get_url()
		+ "/api/method/twilio_call_log_endpoint"
	)
	https_status_callback_url = force_https(status_callback_url)

	log = frappe.get_doc(
		{
			"doctype": "Twilio Call Log",
			"type": "Call",
			"purpose": purpose,
			"to_no": to_number,
			"from_no": from_number,
			"attempt_no": 1,
			"max_attempts": settings.total_recurring_call,
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
		frappe.log_error(
			frappe.get_traceback(),
			"Twilio Call Initiation Failed"
		)
		raise

	return {
		"log": log.name,
		"call_sid": call.sid,
	}


# -------------------------------------------------------------------
# Retry Executor (called by scheduler via enqueue)
# -------------------------------------------------------------------

def retry_twilio_call(log_name):
	log = frappe.get_doc("Twilio Call Log", log_name)

	if log.call_status == "completed":
		return

	if log.attempt_no >= log.max_attempts:
		return

	# clear retry marker so it doesn't loop
	log.db_set("next_retry_at", None)

	from twilio_integration.twilio_integration.twilio_handler import Twilio

	twilio = Twilio.connect()
	if not twilio:
		return

	client = Client(
		twilio.account_sid,
		twilio.settings.get_password("auth_token"),
	)

	status_callback_url = (
		get_url()
		+ "/api/method/twilio_integration.twilio_integration.doctype.twilio_call_log.twilio_call_log.twilio_call_log_endpoint"
	)

	twiml_url = json.loads(log.response).get("twiml_url")

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
		}
	)


# -------------------------------------------------------------------
# Scheduler Processor (runs every minute)
# -------------------------------------------------------------------

def process_pending_retries():
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
		)


# -------------------------------------------------------------------
# Callback Webhook (drives retries)
# -------------------------------------------------------------------

@frappe.whitelist(allow_guest=True)
def twilio_call_log_endpoint():
	raw_data = frappe.request.get_data(as_text=True)
	content_type = frappe.request.headers.get("Content-Type", "")

	if not raw_data:
		return

	try:
		if "application/json" in content_type:
			payload = json.loads(raw_data)
		else:
			payload = parse_qs(raw_data)

		doc = frappe.get_doc(
			{
				"doctype": "Twilio Call Log",
				"type": "Callback",
				"response": json.dumps(payload),
			}
		)
		doc.insert(ignore_permissions=True)

		call_sid = _get_value(payload, "CallSid")
		call_status = _get_value(payload, "CallStatus")

		if call_sid and call_status != "completed":
			parent = frappe.db.exists(
				"Twilio Call Log",
				{"call_sid": call_sid, "type": "Call"},
			)

			if parent:
				log = frappe.get_doc("Twilio Call Log", parent)

				if log.attempt_no < log.max_attempts:
					log.db_set(
						"next_retry_at",
						add_to_date(
							now_datetime(),
							log.buffer_time,
						),
					)

	except Exception:
		frappe.log_error(
			frappe.get_traceback(),
			"Twilio Callback Failure"
		)
		frappe.throw("Webhook processing failed")

	finally:
		frappe.db.commit()

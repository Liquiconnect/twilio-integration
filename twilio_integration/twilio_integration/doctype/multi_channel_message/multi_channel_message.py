# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import validate_email_address, split_emails
import re
import json
from frappe.utils import cstr
from twilio_integration.twilio_integration.doctype.whatsapp_message.whatsapp_message import (
	WhatsAppMessage,
)
from urllib.parse import quote, urlencode, quote
from frappe.utils import get_url

class MultiChannelMessage(Document):
	def on_submit(self):
		# Send mail only when Approved + Email channel
		if self.workflow_state != "Approved":
			return

		if self.channel == "Email":
			self.trigger_send_mail_alert()
		if self.channel == "WhatsApp":
			self.trigger_send_whatsapp_alert()
		if self.channel == "Call":
			self.trigger_call_channel()

	def trigger_send_whatsapp_alert(self):
		template_name = "send_mc_alert_without_attachment"
		if not self.recipients_number:
			frappe.throw("WhatsApp recipients not found")
		message = {
			"1": self.recipients_name,
			"2": self.whatsapp_message_content
		}
		media_url = None

		if self.attachment:
			template_name  = "copy_send_mc_alert_with_attachment"
			media_url = self.get_attachment_url()
			media_url = quote(media_url, safe="/:")
			message["3"] = media_url

		content_sid = frappe.db.get_value(
			"WhatsApp Template Reference",
			{
				"name": template_name,
				"disabled": 0
			},
			"content_sid"
		)
		if not content_sid:
			frappe.throw("WhatsApp template not configured")
		
		numbers = self.split_number_strict(self.recipients_number)
		WhatsAppMessage.send_whatsapp_message(
			receiver_list=numbers,
			content_sid=content_sid,
			content_variables=json.dumps(message),
			doctype=self.doctype,
			docname=self.name,
			media= media_url
		)

	def get_attachment_url(self):
		"""
		Returns a valid media URL for WhatsApp:
		- self.attachment can be a link or a Frappe File
		- Supports PDF, images, S3 stored files
		"""
		if not self.attachment:
			return None

		# Check if attachment is a Frappe File
		file_doc = frappe.get_all(
			"File",
			filters={"name": self.attachment},
			fields=["file_url"],
			limit=1
		)
		if file_doc:
			return file_doc[0].file_url

		# Otherwise, assume it's a direct link / URL
		return self.attachment

	def trigger_send_mail_alert(self):
		if not self.recipients:
			frappe.throw("Recipients are required to send Email")
		attachments = []

		# attachment field already contains File URL or file name
		if self.attachment:
			attachments.append({
				"file_url": self.attachment
			})

		frappe.enqueue(
			queue="short",
			method=frappe.sendmail,
			recipients=self._split_lines(self.recipients),
			sender=self.sender_email,
			cc=self._split_lines(self.cc),
			bcc=self._split_lines(self.bcc),
			subject=self.subject,
			message=self.email_content,
			reference_doctype=self.doctype,
			reference_name=self.name,
			attachments=attachments,
			expose_recipients="header",
			now=True,
		)

	def trigger_call_channel(self):
		if self.channel != "Call":
			return

		if not self.recipients_number:
			frappe.throw("Recipient number is required for Call")

		if not self.whatsapp_message_content:
			frappe.throw("Message is required to initiate call")

		# Build TwiML URL
		query_params = {
			"msg": self.whatsapp_message_content,
			"name": self.recipients_name or 'Customer'
		}
		query_string = urlencode(query_params)
		url_prefix = f'/api/method/twilio_integration.api.recieve_call_params.twiml_say_message?{query_string}'
		twiml_url = frappe.utils.get_url() + url_prefix
		numbers = self.split_number_strict(self.recipients_number)
		for num in numbers:
			frappe.call(
				"twilio_integration.twilio_integration.doctype.twilio_call_log.twilio_call_log.initiate_twilio_call",
				to_number=num,
				twiml_url=twiml_url,
				purpose="Multi Channel Call",
				reference_doctype=self.doctype,
				reference_name=self.name,
			)

	def _split_lines(self, value):
		"""Convert newline-separated values to list"""
		if not value:
			return []
		return [v.strip() for v in value.split("\n") if v.strip()]

	def validate(self):	
		self.validate_email()
		self.validate_whatsapp()
		self.update_message_format()
		self.update_duplicate_entries()

	def validate_email(self):
		"""Validate Email Addresses of Recipients and CC"""
		if not self.channel == "Email":
			return

		self.recipients = self._validate_and_format_emails(
				self.recipients, "Recipients"
			)

		self.cc = self._validate_and_format_emails(
			self.cc, "CC"
		)

		self.bcc = self._validate_and_format_emails(
			self.bcc, "BCC"
		)

	def validate_whatsapp(self):
		if self.channel not in  ["WhatsApp", "Call"]:
			return

		if not self.recipients_number:
			frappe.throw("Please enter at least one WhatsApp number")
		numbers = self.split_number_strict(self.recipients_number)

		# If split_number_strict throws, it will stop here
		self.recipients_number = "\n".join(numbers)
		if self.attachment and not self.attachment.lower().endswith("pdf"):
			frappe.throw("File Attachment for whatsapp should be PDF")

	def split_number_strict(self, txt):
		"""
		Strictly validate Indian WhatsApp numbers.
		- Accept multiple numbers separated by comma, space, or newline.
		- Must be exactly 10 digits (assume Indian) or 12 digits starting with 91 (with optional +).
		- Throw error immediately if any invalid number exists.
		- Return list of formatted numbers with +91 prefix, deduplicated.
		"""
		if not txt:
			frappe.throw("Please enter at least one WhatsApp number")

		# Split input by commas, newlines, or whitespace
		parts = re.split(r"[,\n\s]+", txt)
		numbers = []

		for part in parts:
			part = part.strip()
			if not part:
				continue

			# Remove leading + for validation
			stripped = part.lstrip("+")

			# 10-digit number
			if re.fullmatch(r"\d{10}", stripped):
				numbers.append(f"+91{stripped}")
			# 12-digit number starting with 91
			elif re.fullmatch(r"91\d{10}", stripped):
				numbers.append(f"+{stripped}")
			else:
				frappe.throw(f"Invalid WhatsApp number: {part}")

		if not numbers:
			frappe.throw("Please enter at least one valid WhatsApp number")

		# Deduplicate while preserving order
		return list(dict.fromkeys(numbers))

	def update_message_format(self):
		if self.channel == "WhatsApp":
			self.update_whatsapp_message_format()

	def update_whatsapp_message_format(self):
		if not self.whatsapp_message_content:
			return
		# Replace newlines and multiple spaces with single space
		self.whatsapp_message_content = " ".join(self.whatsapp_message_content.split())


	def update_duplicate_entries(self):
		"""
		Deduplicate emails within each field AND across recipients, cc, bcc.
		Deduplicate WhatsApp numbers separately.
		"""
		# Step 1: Deduplicate within each field
		self.recipients = self._dedupe_emails(self.recipients)
		self.cc = self._dedupe_emails(self.cc)
		self.bcc = self._dedupe_emails(self.bcc)

		# Step 2: Deduplicate across fields
		seen = set()
		
		def remove_duplicates_across_field(field_value):
			if not field_value:
				return ""
			emails = [e.strip() for e in field_value.split("\n") if e.strip()]
			new_list = []
			for email in emails:
				key = email.lower()
				if key not in seen:
					seen.add(key)
					new_list.append(email)
			return "\n".join(new_list)
		
		self.recipients = remove_duplicates_across_field(self.recipients)
		self.cc = remove_duplicates_across_field(self.cc)
		self.bcc = remove_duplicates_across_field(self.bcc)

		# WhatsApp / Phone numbers
		self.recipients_number = self._dedupe_numbers(self.recipients_number)


	def _dedupe_emails(self, value):
		if not value:
			return value

		# Normalize to newline first
		emails = [e.strip() for e in re.split(r"[,\n\s]+", value) if e.strip()]
		emails = unique_preserve_order(emails)

		return "\n".join(emails)


	def _dedupe_numbers(self, value):
		if not value:
			return value

		numbers = [n.strip() for n in re.split(r"[,\n\s]+", value) if n.strip()]
		numbers = unique_preserve_order(numbers)

		return "\n".join(numbers)


	def _validate_and_format_emails(self, value, label):
		if not value:
			return value

		# Split by comma, newline, or space
		parts = re.split(r"[,\n\s]+", cstr(value))

		valid_emails = []
		seen = set()

		for email in parts:
			email = email.strip()
			if not email:
				continue

			# Validate each email individually
			validate_email_address(email, throw=True)

			key = email.lower()
			if key not in seen:
				seen.add(key)
				valid_emails.append(email)

		if not valid_emails:
			frappe.throw(f"Please enter at least one valid email in {label}")

		# Store one email per line
		return "\n".join(valid_emails)

def unique_preserve_order(items):
	seen = set()
	result = []
	for item in items:
		key = item.lower() if isinstance(item, str) else item
		if key not in seen:
			seen.add(key)
			result.append(item)
	return result

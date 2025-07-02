# For license information, please see license.txt

import frappe
import json
from frappe.model.document import Document
from six import string_types
from frappe.utils.password import get_decrypted_password
from frappe.utils import get_site_url
from frappe import _
from ...twilio_handler import Twilio

class WhatsAppMessage(Document):
	def send(self):
		client = Twilio.get_twilio_client()
		message_dict = self.get_message_dict()
		response = frappe._dict()

		try:
			response = client.messages.create(**message_dict)
			self.sent_received = 'Sent'
			self.status = response.status.title()
			self.id = response.sid
			self.send_on = response.date_sent
			self.save(ignore_permissions=True)
		
		except Exception as e:
			self.db_set('status', "Error")
			frappe.log_error(message=_(e), title = _('Twilio WhatsApp Message Error'))

	def get_message_dict(self):
		args = {
			'from_': self.from_,
			'to': self.to,
		}
		if self.content_sid and self.content_variables:
			args.update({"content_sid": self.content_sid, "content_variables": self.content_variables})
		elif self.message:
			args.update({'body': self.message})
		if self.media_link:
			args['media_url'] = [self.media_link]

		return args

	@classmethod
	def send_whatsapp_message(self, receiver_list, doctype, docname, media=None, content_sid=None, content_variables=None, message=None):
		if isinstance(receiver_list, string_types):
			receiver_list = json.loads(receiver_list)
			if not isinstance(receiver_list, list):
				receiver_list = [receiver_list]

		for rec in receiver_list:
			message = self.store_whatsapp_message(rec, doctype, docname, media,  content_sid, content_variables, message)
			message.send()

	def store_whatsapp_message(to, doctype=None, docname=None, media=None, content_sid=None, content_variables=None, message=None):
		sender = frappe.db.get_single_value('Twilio Settings', 'whatsapp_no')
		wa_msg = frappe.get_doc({
				'doctype': 'WhatsApp Message',
				'from_': 'whatsapp:{}'.format(sender),
				'to': 'whatsapp:{}'.format(to),
				'message': message if message else "Nill",
				'reference_doctype': doctype,
				'reference_document_name': docname,
				'media_link': media
			}).insert(ignore_permissions=True)
		wa_msg.content_sid = content_sid
		wa_msg.content_variables = content_variables
		return wa_msg

def incoming_message_callback(args):
	wa_msg = frappe.get_doc({
			'doctype': 'WhatsApp Message',
			'from_': args.From,
			'to': args.To,
			'message': args.Body,
			'profile_name': args.ProfileName,
			'sent_received': args.SmsStatus.title(),
			'id': args.MessageSid,
			'send_on': frappe.utils.now(),
			'status': 'Received'
		}).insert(ignore_permissions=True)


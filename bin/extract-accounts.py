#!/usr/bin/python
# -*- encoding: utf-8 -*-
from __future__ import division

import csv
import os
import re
import sys

from xml.etree import cElementTree

GAAP_FIELDS = [
	"ProfitLossAccountReserve",
	"TangibleFixedAssetsCostOrValuation",
	"IntangibleFixedAssetsCostOrValuation",
	"TurnoverGrossOperatingRevenue",
	"CostSales",
	"GrossProfitLoss",
    "OperatingProfitLoss",
    "ProfitLossForPeriod",
    "InterestPayableSimilarCharges",
    "ProfitLossOnOrdinaryActivitiesBeforeTax",
    "TotalRecognisedGainLossForPeriod",
    "StaffCosts",
]

header_fields = []
for gaap_field in GAAP_FIELDS:
	header_fields += [ gaap_field + "_start_date", gaap_field + "_end_date", gaap_field + "_value" ]

w = csv.writer(sys.stdout)
w.writerow([
	"company_number", "balance_sheet_date", "registered_name"
	] + header_fields)

def parse_nsmap(file):
	namespaces_by_element = {}
	events = "start", "start-ns", "end-ns"

	root = None
	ns_map = []

	for event, elem in cElementTree.iterparse(file, events):
		if event == "start-ns":
			prefix, url = elem
			ns_map.append((url, prefix))
		elif event == "end-ns":
			ns_map.pop()
		elif event == "start":
			if root is None:
				root = elem
			namespaces_by_element[elem] = dict(ns_map)

	return cElementTree.ElementTree(root), namespaces_by_element

def get_element_text(element):
	text = element.text or ""
	for e in element:
		text += get_element_text(e) + " "
	text += (element.tail or "")
	return re.sub(r"\s+", " ", text).strip()

def xml_serialise(element):
	return cElementTree.tostring(element, encoding="utf-8")

def extract_accounts(filepath, filetype):
	if filetype == "html":
		return extract_accounts_inline(filepath)
	elif filetype == "xml":
		return extract_accounts_xml(filepath)
	else:
		raise Exception("Unknown filetype: " + filetype)

def get_dates(period):
	if period is None:
		return None, None
	instant = period.find("{http://www.xbrl.org/2003/instance}instant")
	if instant is not None:
		v = instant.text
		return (v, v)
	else:
		start_date = period.find("{http://www.xbrl.org/2003/instance}startDate")
		end_date = period.find("{http://www.xbrl.org/2003/instance}endDate")
		if start_date is None or end_date is None:
			return (None, None)
		return (start_date.text, end_date.text)

def get_contexts(x):
	contexts = {}
	for e in x.findall(".//{http://www.xbrl.org/2003/instance}context"):
		if e.find("./{http://www.xbrl.org/2003/instance}entity/{http://www.xbrl.org/2003/instance}segment"):
			# Ignore contexts that refer to a segment
			contexts[e.get("id")] = None
		else:
			contexts[e.get("id")] = e.find("./{http://www.xbrl.org/2003/instance}period")
	return contexts

def get_value(e):
	sign = -1 if e.get("sign", "") == "-" else +1
	text = e.text
	if text == "-": return 0
	return sign * float(re.sub(r",", "", text)) * 10**int(e.get("scale", "0"))

def extract_accounts_inline(filepath):
	print >>sys.stderr, "Loading {}...".format(filepath)
	
	name = None
	x, namespaces_by_element = parse_nsmap(filepath)
	contexts = get_contexts(x)
	
	for e in x.findall(".//{http://www.xbrl.org/2008/inlineXBRL}nonNumeric"):
		prefix = namespaces_by_element[e].get("http://www.xbrl.org/uk/cd/business/2009-09-01")
		if prefix is not None and e.get("name") == prefix + ":EntityCurrentLegalOrRegisteredName":
			name = get_element_text(e)
	
	result = [ name ]
	for gaap_field in GAAP_FIELDS:
		result += get_gaap_value(x, namespaces_by_element, contexts, gaap_field)
	
	return result

def get_gaap_value(x, namespaces_by_element, contexts, element_name):
	all_values = []
	for e in x.findall(".//{http://www.xbrl.org/2008/inlineXBRL}nonFraction"):
		prefix = namespaces_by_element[e].get("http://www.xbrl.org/uk/gaap/core/2009-09-01")
		if prefix is not None and e.get("name") == prefix + ":" + element_name:
			period = contexts[e.get("contextRef")]
			dates = get_dates(period)
			if dates:
				all_values.append((dates, get_value(e)))
	
	if not all_values:
		return None, None, None
	else:
		dates, value = max(all_values, key=lambda(dates,x): dates)
		return dates + (value,)

def get_gaap_value_xml(x, namespaces_by_element, contexts, element_name):
	all_values = []
	for e in x.findall(".//{http://www.xbrl.org/uk/fr/gaap/pt/2004-12-01}" + element_name):
		period = contexts[e.get("contextRef")]
		dates = get_dates(period)
		if dates:
			all_values.append((dates, get_value(e)))
	
	if not all_values:
		return None, None
	else:
		dates, value = max(all_values, key=lambda(dates,x): dates)
		return dates + (value,)

def extract_accounts_xml(filepath):
	print >>sys.stderr, "Loading {}...".format(filepath)
	x, namespaces_by_element = parse_nsmap(filepath)
	contexts = get_contexts(x)
	name = x.find(".//{http://www.xbrl.org/uk/fr/gcd/2004-12-01}EntityCurrentLegalName").text
	
	result = [ name ]
	for gaap_field in GAAP_FIELDS:
		result += get_gaap_value_xml(x, namespaces_by_element, contexts, gaap_field)
	
	return result

def writerow(row):
	w.writerow([
		x.encode("utf-8") if isinstance(x, unicode) else x
		for x in row
	])

def process(path):
	filename = os.path.basename(path)
	mo = re.match("^(Prod\d+_\d+)_([^_]+)_(\d\d\d\d\d\d\d\d)\.(html|xml)", filename)
	run_code, company, date, filetype = mo.groups()
	accounts = extract_accounts(path, filetype)
	writerow([company, date] + accounts)

def process_dir(d):
	for f in os.listdir(d):
		p = os.path.join(d, f)
		try:
			process(p)
		except:
			import traceback
			print >>sys.stderr, "\n\nException processing: " + p
			traceback.print_exc(file=sys.stderr)
			print >>sys.stderr, "\n\n"

if len(sys.argv) > 1:
	for f in sys.argv[1:]:
		if os.path.isdir(f):
			process_dir(f)
		else:
			process(f)
else:
	for x in os.listdir("data"):
		d = os.path.join("data", x)
		if os.path.isdir(d):
			process_dir(d)


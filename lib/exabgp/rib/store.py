# encoding: utf-8
"""
store.py

Created by Thomas Mangin on 2009-11-05.
Copyright (c) 2009-2013 Exa Networks. All rights reserved.
"""

from exabgp.bgp.message.direction import IN,OUT
from exabgp.bgp.message.update import Update

# XXX: FIXME: we would not have to use so many setdefault if we pre-filled the dicts with the families

class Store (object):
	def __init__ (self,cache):
		# XXX: FIXME: we can decide to not cache the routes we seen and let the backend do it for us and save the memory
		self._watchdog = {}
		self.cache = cache
		self._announced = {}
		self._cache_attribute = {}
		self._modify_nlri = {}
		self._modify_sorted = {}


	def every_changes (self):
		# we use list() to make a snapshot of the data at the time we run the command
		for family in list(self._announced.keys()):
			for change in self._announced[family].values():
				if change.nlri.action == OUT.announce:
					yield change

	def dump (self):
		# This function returns a hash and not a list as "in" tests are O(n) with lists and O(1) with hash
		# and with ten thousands routes this makes an enormous difference (60 seconds to 2)
		changes = {}
		for family in self._announced.keys():
			for change in self._announced[family].values():
				if change.nlri.action == OUT.announce:
					changes[change.index()] = change
		return changes

	def resend_known (self):
		for change in self.every_changes():
			self.insert_announced(change,True)

	def insert_announced_watchdog (self,change):
		watchdog = change.attributes.watchdog()
		withdraw = change.attributes.withdraw()
		if watchdog:
			if withdraw:
				self._watchdog.setdefault(watchdog,{}).setdefault('-',{})[change.nlri.index()] = change
				return True
			self._watchdog.setdefault(watchdog,{}).setdefault('+',{})[change.nlri.index()] = change
		self.insert_announced(change)
		return True

	def announce_watchdog (self,watchdog):
		if watchdog in self._watchdog:
			for change in self._watchdog[watchdog].get('-',{}).values():
				change.nlri.action = OUT.announce
				self.insert_announced(change)
				self._watchdog[watchdog].setdefault('+',{})[change.nlri.index()] = change
				self._watchdog[watchdog]['-'].pop(change.nlri.index())

	def withdraw_watchdog (self,watchdog):
		if watchdog in self._watchdog:
			for change in self._watchdog[watchdog].get('+',{}).values():
				change.nlri.action = OUT.withdraw
				self.insert_announced(change)
				self._watchdog[watchdog].setdefault('-',{})[change.nlri.index()] = change
				self._watchdog[watchdog]['+'].pop(change.nlri.index())

	def insert_received (self,change):
		if not self.cache:
			return
		elif change.nlri.action == IN.announced:
			self._announced[change.nlri.index()] = change
		else:
			self._announced.pop(change.nlri.index(),None)

	def insert_announced (self,change,force=False):
		# WARNING : this function can run while we are in the updates() loop

		# self._announced[fanily][nlri-index] = change

		# XXX: FIXME: if we fear a conflict of nlri-index between family (very very unlikely)
		# XXX: FIXME: then we should preprend the index() with the AFI and SAFI

		# self._modify_nlri[nlri-index] = change : we are modifying this nlri
		# self._modify_sorted[attr-index][nlri-index] = change : add or remove the nlri
		# self._cache_attribute[attr-index] = change
		# and it allow to overwrite change easily :-)

		# import traceback
		# traceback.print_stack()
		# print "inserting", change.extensive()

		change_nlri_index = change.nlri.index()
		change_attr_index = change.attributes.index()

		dict_sorted = self._modify_sorted
		dict_nlri = self._modify_nlri
		dict_attr = self._cache_attribute

		if change_nlri_index in dict_nlri:
			old_attr_index = dict_nlri[change_nlri_index].attributes.index()
			# pop removes the entry
			old_change = dict_nlri.pop(change_nlri_index)
			# do not delete dict_attr, other routes may use it
			del dict_sorted[old_attr_index][change_nlri_index]
			if not dict_sorted[old_attr_index]:
				del dict_sorted[old_attr_index]
			if not force and old_change.nlri.action == OUT.announce and change.nlri.action == OUT.withdraw:
				return True

		dict_sorted.setdefault(change_attr_index,{})[change_nlri_index] = change
		dict_nlri[change_nlri_index] = change
		if change_attr_index not in dict_attr:
			dict_attr[change_attr_index] = change

		if change.nlri.action == OUT.withdraw:
			if not self.cache:
				return True
			return change_nlri_index in self._announced or change_nlri_index in dict_nlri
		return True

	def updates (self,grouped):
		dict_sorted = self._modify_sorted
		dict_nlri = self._modify_nlri
		dict_attr = self._cache_attribute

		for attr_index,dict_new_nlri in list(dict_sorted.iteritems()):
			if not dict_new_nlri:
				continue

			attributes = dict_attr[attr_index].attributes

			# we NEED the copy provided by list() here as clear_sent or insert_announced can be called while we iterate
			changed = list(dict_new_nlri.itervalues())

			if grouped:
				update = Update([dict_nlri[nlri_index].nlri for nlri_index in dict_new_nlri],attributes)
				for change in changed:
					nlri_index = change.nlri.index()
					del dict_new_nlri[nlri_index]
					del dict_nlri[nlri_index]
				# only yield once we have a consistent state, otherwise it will go wrong
				# as we will try to modify things we are using
				yield update
			else:
				updates = [Update([change.nlri,],attributes) for change in changed]
				for change in changed:
					nlri_index = change.nlri.index()
					del dict_new_nlri[nlri_index]
					del dict_nlri[nlri_index]
				# only yield once we have a consistent state, otherwise it will go wrong
				# as we will try to modify things we are using
				for update in updates:
					yield update

			if self.cache:
				announced = self._announced
				for change in changed:
					if change.nlri.action == OUT.announce:
						announced.setdefault(change.nlri.family(),{})[change.nlri.index()] = change
					else:
						family = change.nlri.family()
						if family in announced:
							announced[family].pop(change.nlri.index(),None)

	def clear_sent (self):
		# WARNING : this function can run while we are in the updates() loop too !
		self._modify_nlri = {}
		self._modify_sorted = {}

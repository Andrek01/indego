#!/usr/bin/env python3
# vim: set encoding=utf-8 tabstop=4 softtabstop=4 shiftwidth=4 expandtab
#########################################################################
#  Copyright 2018 Marco Düchting                   Marco.Duechting@gmx.de
#  Copyright 2018 Bernd Meiners                     Bernd.Meiners@mail.de
#  Copyright 2019 Andre Kohler              andre.kohler01@googlemail.com
#########################################################################
#  This file is part of SmartHomeNG.   
#
#  Sample plugin for new plugins to run with SmartHomeNG version 1.6 and
#  upwards.
#
#  SmartHomeNG is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  SmartHomeNG is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with SmartHomeNG. If not, see <http://www.gnu.org/licenses/>.
#
#########################################################################


import time
import base64
import os
import ast

import json
#import http.client
from dateutil import tz
import sys


import requests

from lib.module import Modules
from lib.model.smartplugin import *
from lib.item import Items
from lib.shtime import Shtime
from datetime import datetime
from datetime import date
from bs4 import BeautifulSoup
import base64




# If a package is needed, which might be not installed in the Python environment,
# import it like this:
#
# try:
#     import <exotic package>
#     REQUIRED_PACKAGE_IMPORTED = True
# except:
#     REQUIRED_PACKAGE_IMPORTED = False


class Indego(SmartPlugin):
    """
    Main class of the Indego Plugin. Does all plugin specific stuff and provides
    the update functions for the items
    """
    PLUGIN_VERSION = '3.0.0'

    def __init__(self, sh, *args, **kwargs):
        """
        Initalizes the plugin. The parameters describe for this method are pulled from the entry in plugin.conf.

        :param sh:  **Deprecated**: The instance of the smarthome object. For SmartHomeNG versions 1.4 and up: **Don't use it**!
        :param *args: **Deprecated**: Old way of passing parameter values. For SmartHomeNG versions 1.4 and up: **Don't use it**!
        :param **kwargs:**Deprecated**: Old way of passing parameter values. For SmartHomeNG versions 1.4 and up: **Don't use it**!

        If you need the sh object at all, use the method self.get_sh() to get it. There should be almost no need for
        a reference to the sh object any more.

        The parameters *args and **kwargs are the old way of passing parameters. They are deprecated. They are imlemented
        to support oder plugins. Plugins for SmartHomeNG v1.4 and beyond should use the new way of getting parameter values:
        use the SmartPlugin method get_parameter_value(parameter_name) instead. Anywhere within the Plugin you can get
        the configured (and checked) value for a parameter by calling self.get_parameter_value(parameter_name). It
        returns the value in the datatype that is defined in the metadata.
        """
        from bin.smarthome import VERSION
        if '.'.join(VERSION.split('.', 2)[:2]) <= '1.5':
            self.logger = logging.getLogger(__name__)

        # get the parameters for the plugin (as defined in metadata plugin.yaml):
        #   self.param1 = self.get_parameter_value('param1')

        self.user = ''
        self.password = ''
        self.credentials = self.get_parameter_value('indego_credentials').encode('utf-8')
        if (self.credentials != b'None'):
            self.credentials = base64.decodebytes(self.credentials).decode('utf-8')
        
        self.img_pfad = self.get_parameter_value('img_pfad')
        self.cycle = self.get_parameter_value('cycle')
        self.indego_url = self.get_parameter_value('indego_url')
        self.parent_item = self.get_parameter_value('parent_item')
        self.path_2_weather_pics = self.get_parameter_value('path_2_weather_pics') 
        
        self.items = Items.get_instance()
        self.shtime = Shtime.get_instance()
        self.sh = self.get_sh()

        self.expiration_timestamp = 0.0
        self.last_login_timestamp = 0.0
        self.logged_in = False
        
        self.context_id = ''
        self.user_id = ''
        self.alm_sn = ''
        self.alert_reset = True
        
        self.logged_in = False

        self.add_keys = {}
        self.cal_update_count = 0
        self.cal_update_running = False
        
        self.cal_upate_count_pred = 0
        self.cal_pred_update_running = False
        
        self.calendar_count_mow = []
        self.calendar_count_pred = []
        
        self.position_detection = False
        self.position_count = 0

        # Check for initialization errors:
        if not self.indego_url:
           self._init_complete = False
           return

        if not self.parent_item:
           self._init_complete = False
           return
        self.states = {}
        
        # The following part of the __init__ method is only needed, if a webinterface is being implemented:

        # if plugin should start even without web interface
        self.init_webinterface()

        # if plugin should not start without web interface
        # if not self.init_webinterface():
        #     self._init_complete = False

        return

    def run(self):
        """
        Run method for the plugin
        """
        self.logger.debug("Run method called")
        if (self.credentials != b'None'):
            self.user = self.credentials.split(":")[0]
            self.password = self.credentials.split(":")[1]
        # taken from Init of the plugin
        if (self.user != '' and self.password != ''):
            self._auth()
            self.logged_in = self._check_auth()

        # start the refresh timers
        self.scheduler_add('operating_data',self.get_operating_data,cycle = 300)
        self.scheduler_add('state', self.state, cycle = self.cycle)
        self.scheduler_add('alert', self.alert, cycle=30)
        self.scheduler_add('get_calendars', self._get_calendars, cycle=300)
        self.scheduler_add('check_login_state', self._check_login_state, cycle=90)
        self.scheduler_add('device_data', self.device_data, cycle=120)
        self.scheduler_add('get_weather', self.get_weather, cycle=600)
        self.scheduler_add('get_next_time', self.get_next_time, cycle=300)
        
        self.alive = True
        # if you need to create child threads, do not make them daemon = True!
        # They will not shutdown properly. (It's a python bug)
       
        

    def stop(self):
        """
        Stop method for the plugin
        """
        self.get_sh().scheduler.remove('operating_data')
        self.get_sh().scheduler.remove('state')
        self.get_sh().scheduler.remove('alert')
        self.get_sh().scheduler.remove('get_calendars')
        self.get_sh().scheduler.remove('check_login_state')
        self.get_sh().scheduler.remove('device_date')
        self.get_sh().scheduler.remove('get_weather')
        self.get_sh().scheduler.remove('get_next_time')
        
        self._delete_auth()   # Log off
        self.logger.debug("Stop method called")
        self.alive = False

    def parse_item(self, item):
        """
        Default plugin parse_item method. Is called when the plugin is initialized.
        The plugin can, corresponding to its attribute keywords, decide what to do with
        the item in future, like adding it to an internal array for future reference
        :param item:    The item to process.
        :return:        If the plugin needs to be informed of an items change you should return a call back function
                        like the function update_item down below. An example when this is needed is the knx plugin
                        where parse_item returns the update_item function when the attribute knx_send is found.
                        This means that when the items value is about to be updated, the call back function is called
                        with the item, caller, source and dest as arguments and in case of the knx plugin the value
                        can be sent to the knx with a knx write function within the knx plugin.
        """
        if self.has_iattr(item.conf, 'indego_command'):
            self.logger.debug("Item '{}' has attribute '{}' found with {}".format( item, 'indego_command', self.get_iattr_value(item.conf, 'indego_command')))
            return self.update_item

        if self.has_iattr(item.conf, 'indego_config'):
            self.logger.debug("Item '{}' has attribute '{}' found with {}".format(item, 'indego_plugin_handled', self.get_iattr_value(item.conf, 'indego_config')))
            return self.update_item
        
        if self.has_iattr(item.conf, 'indego_plugin_handled'):
            self.logger.debug("Item '{}' has attribute '{}' found with {}".format(item, 'indego_plugin_handled', self.get_iattr_value(item.conf, 'indego_plugin_handled')))
            return self.update_item
        
        if item.property.name ==  self.parent_item+'.states_str':
            newStruct = {}
            myStruct= json.loads(item())
            for entry in myStruct:
                newStruct[int(entry)]=myStruct[entry]
            self.states = newStruct
        ################################################
        '''
        if item.property.name ==  self.parent_item+'.calendar_list':
            self.logger.debug("Item '{}' has attribute '{}' found with {}".format(item, 'calendar_list', self.get_iattr_value(item.conf, 'calendar_list')))
            return self.update_item
            
        
        if item.property.name ==  self.parent_item+'.calendar_predictive_list':
            self.logger.debug("Item '{}' has attribute '{}' found with {}".format(item, 'calendar_list', self.get_iattr_value(item.conf, 'calendar_list')))
            return self.update_item
        
        if item.property.name ==  self.parent_item+'.calendar_save':
            self.logger.debug("Item '{}' has attribute '{}' found with {}".format(item, 'calendar_list', self.get_iattr_value(item.conf, 'calendar_list')))
            return self.update_item
        
        if item.property.name ==  self.parent_item+'.calendar_predictive_save':
            self.logger.debug("Item '{}' has attribute '{}' found with {}".format(item, 'calendar_list', self.get_iattr_value(item.conf, 'calendar_list')))
            return self.update_item

        if item.property.name ==  self.parent_item+'.alm_mode':
            self.logger.debug("Item '{}' has attribute '{}' found with {}".format(item, 'calendar_list', self.get_iattr_value(item.conf, 'calendar_list')))
            return self.update_item        
        
        if item.property.name == self.parent_item+'.active_mode':
                self.logger.debug("Item '{}' has attribute '{}' found with {}".format(item, 'active_mode', self.get_iattr_value(item.conf, 'active_mode')))
                return self.update_item
        
        if "active_mode" in item.property.name:
                self.logger.debug("Item '{}' has attribute '{}' found with {}".format(item, 'modus', self.get_iattr_value(item.conf, 'modus')))
                return self.update_item
        
        if "active_mode" in item.property.name:
                self.logger.debug("Item '{}' has attribute '{}' found with {}".format(item, 'modus', self.get_iattr_value(item.conf, 'modus')))
                return self.update_item
        
        if "refresh" in item.property.name:
                self.logger.debug("Item '{}' has attribute '{}' found with {}".format(item, 'modus', self.get_iattr_value(item.conf, 'modus')))
                return self.update_item
        
        if "store_sms_profile" in item.property.name:
                self.logger.debug("Item '{}' has attribute '{}' found with {}".format(item, 'modus', self.get_iattr_value(item.conf, 'modus')))
                return self.update_item
        
        if "visu.alerts_set_read" in item.property.name:
                self.logger.debug("Item '{}' has attribute '{}' found with {}".format(item, 'modus', self.get_iattr_value(item.conf, 'modus')))
                return self.update_item
        
        if "visu.alerts_set_clear" in item.property.name:
                self.logger.debug("Item '{}' has attribute '{}' found with {}".format(item, 'modus', self.get_iattr_value(item.conf, 'modus')))
                return self.update_item
        
        if "wartung.wintermodus" in item.property.name:
                self.logger.debug("Item '{}' has attribute '{}' found with {}".format(item, 'modus', self.get_iattr_value(item.conf, 'modus')))
                return self.update_item        
        
        if "visu.show_mow_track" in item.property.name:
                self.logger.debug("Item '{}' has attribute '{}' found with {}".format(item, 'modus', self.get_iattr_value(item.conf, 'modus')))
                return self.update_item
        
        if "visu.mow_track" in item.property.name:
                self.logger.debug("Item '{}' has attribute '{}' found with {}".format(item, 'modus', self.get_iattr_value(item.conf, 'modus')))
                return self.update_item
        
        if "wartung.update_auto" in item.property.name:
                self.logger.debug("Item '{}' has attribute '{}' found with {}".format(item, 'modus', self.get_iattr_value(item.conf, 'modus')))
                return self.update_item

        if "wartung.update_start" in item.property.name:
                self.logger.debug("Item '{}' has attribute '{}' found with {}".format(item, 'modus', self.get_iattr_value(item.conf, 'modus')))
                return self.update_item
        
        if "webif.garden_map" in item.property.name:
                self.logger.debug("Item '{}' has attribute '{}' found with {}".format(item, 'modus', self.get_iattr_value(item.conf, 'modus')))
                return self.update_item
        
        if "visu.add_svg_images" in item.property.name:
                self.logger.debug("Item '{}' has attribute '{}' found with {}".format(item, 'modus', self.get_iattr_value(item.conf, 'modus')))
                return self.update_item
        
        if "visu.mower_colour" in item.property.name:
                self.logger.debug("Item '{}' has attribute '{}' found with {}".format(item, 'modus', self.get_iattr_value(item.conf, 'modus')))
                return self.update_item
        '''
        return None

    def parse_logic(self, logic):
        """
        Default plugin parse_logic method
        """
        if 'xxx' in logic.conf:
            # self.function(logic['name'])
            pass

    def update_item(self, item, caller=None, source=None, dest=None):
        """
        Item has been updated
    
        This method is called, if the value of an item has been updated by SmartHomeNG.
        It should write the changed value out to the device (hardware/interface) that
        is managed by this plugin.
    
        :param item: item to be updated towards the plugin
        :param caller: if given it represents the callers name
        :param source: if given it represents the source
        :param dest: if given it represents the dest
        """
        # Function when item is triggered by VISU
        if caller != self.get_shortname() and caller != 'Autotimer' and caller != 'Logic':
            # code to execute, only if the item has not been changed by this this plugin:
            self.logger.info("Update item: {}, item has been changed outside this plugin".format(item.id()))
    
            if self.has_iattr(item.conf, 'indego_config'):
                self.logger.debug("update_item was called with item '{}' from caller '{}', source '{}' and dest '{}'".format(item,caller,source,dest))
                ''' Example
                PUT /api/v1/alms/603702021/config
                {"bump_sensitivity": 0 } = normal
                '''
                try:
                    myUrl = self.indego_url + item.conf['indego_config_url'].format(self.alm_sn)
                    myBody = json.loads(item.conf['indego_config'].replace('#',str(item.property.value)))
                    myResult = self._send_config(myUrl, myBody)
                except:
                    self.logger.warning("Error building config for item '{}' from caller '{}', source '{}' and dest '{}'".format(item,caller,source,dest))
    
                
            if item.property.name == self.parent_item+'.calendar_list':
                myList = item()
                self.parse_list_2_cal(myList, self.calendar,'MOW')


            if item.property.name == self.parent_item+'.calendar_predictive_list':
                myList = item()
                self.parse_list_2_cal(myList, self.predictive_calendar,'PRED')
                     

            if item.property.name == self.parent_item+'.active_mode.kalender' and item() == True:
                self.set_childitem('update_active_mode', True)
                self.set_childitem('active_mode', 1)
                self.items.return_item('indego.active_mode.uzsu.schaltuhr').activate(False)
                self.set_childitem('active_mode.smart', False)
                self.set_childitem('active_mode.aus', False)
                self._set_smart(False)
                self.set_childitem('calendar_sel_cal', 2)
                self.set_childitem('calendar_save', True)
                self.set_childitem('alm_mode.str','Übersicht Kalender mähen:')
                self.set_childitem('alm_mode','calendar')
                self.set_childitem('update_active_mode', False)
                self.set_childitem('active_mode.uzsu.schaltuhr.active', False)
                
            if item.property.name == self.parent_item+'.active_mode.aus' and item() == True:
                self.set_childitem('update_active_mode', True)
                self.set_childitem('active_mode', 3)
                self.set_childitem('active_mode.kalender', False)
                self.set_childitem('alm_mode.str','')
                self.set_childitem('active_mode.smart', False)
                self._set_smart(False)
                self.set_childitem('calendar_sel_cal', 0)
                self.set_childitem('calendar_save', True)
                self.set_childitem('alm_mode','manual')
                self.set_childitem('update_active_mode', False)
            
            if item.property.name == self.parent_item+'.active_mode.smart' and item() == True:
                self.set_childitem('update_active_mode', True)
                self.set_childitem('active_mode', 2)
                self.items.return_item('indego.active_mode.uzsu.schaltuhr').activate(False)
                self.set_childitem('alm_mode.str','Übersicht SmartMow mähen:')
                self.set_childitem('active_mode.aus', False)
                self.set_childitem('active_mode.kalender', False)
                self.set_childitem('calendar_sel_cal', 3)
                self.set_childitem('calendar_save', True)
                self._set_smart(True)
                self.set_childitem('alm_mode','smart')
                self.set_childitem('update_active_mode', False)
                self.set_childitem('active_mode.uzsu.schaltuhr.active', False)
            
            
            
            if item.property.name == self.parent_item+'.visu.alerts_set_read':
                self._set_read_messages()
            
            if item.property.name == self.parent_item+'.visu.alerts_set_clear':
                self._set_clear_message()
            
            if item.property.name == self.parent_item+".wartung.update_auto":
                self.set_automatic_updates()
            
            if item.property.name == self.parent_item+".wartung.update_start":
                if  item() == True:
                    self.start_manual_update()
                    item(False)
                
            if item._name == self.parent_item+'.active_mode.uzsu':
                if item() == 10:
                    self.set_childitem('MOW', True)
                if item() == 20:
                    self.set_childitem('RETURN', True)
                if item() == 30:              
                    self.set_childitem('PAUSE', True)
            
            if ("show_uzsu_popup" in item.property.name and item() == True):
                self.set_childitem('visu.fire_uszu_popup','fire_uszu_popup|True' )
            
        
        # Function when item is triggered by anybody, also by plugin

        if item.property.name == self.parent_item+'.alm_mode':
            if   (item() == 'smart'):
                self.set_childitem('active_mode', 2)      
                self.set_childitem('active_mode.aus', False)
                self.set_childitem('active_mode.kalender', False)          
                self.set_childitem('active_mode.smart', True)
                self.items.return_item('indego.active_mode.uzsu.schaltuhr').activate(False)
            elif (item() == 'calendar'):
                self.set_childitem('active_mode', 1)
                self.set_childitem('active_mode.aus', False)
                self.set_childitem('active_mode.kalender', True)          
                self.set_childitem('active_mode.smart', False)
                self.items.return_item('indego.active_mode.uzsu.schaltuhr').activate(False)
            elif (item() == 'manual'):
                self.set_childitem('active_mode', 3)
                self.set_childitem('active_mode.aus', True)
                self.set_childitem('active_mode.kalender', False)          
                self.set_childitem('active_mode.smart', False)
            
            
        if self.has_iattr(item.conf, 'indego_command'):
            self.logger.debug("Item '{}' has attribute '{}' triggered {}".format( item, 'indego_command', self.get_iattr_value(item.conf, 'indego_command')))
            try:    
                self.send_command(item, caller=None, source=None, dest=None)
            except:
                    self.logger.warning("Error sending command for item '{}' from caller '{}', source '{}' and dest '{}'".format(item,caller,source,dest))
        
        if item.property.name == self.parent_item+'.visu.store_sms_profile' and item() == True:
                self.smart_mow_settings("write")
                self.set_childitem('visu.store_sms_profile', False)
                    
                    
        if item.property.name == self.parent_item+'.calendar_save' and item() == True:
            self.set_childitem('calendar_result', "speichern gestartet")
            # Now Save the Calendar on Bosch-API
            self.cal_update_count = 0
            self._auto_mow_cal_update()


        if item.property.name == self.parent_item+'.calendar_predictive_save' and item() == True:
            self.set_childitem('calendar_predictive_result', "speichern gestartet")
            # Now Save the Calendar on Bosch-API
            self.upate_count_pred = 0
            self._auto_pred_cal_update()
        
        if "active_mode" in item.property.name:
            self.set_childitem('visu.cal_2_show','cal2show|'+str(self.get_childitem('active_mode')))
        
        if "wartung.wintermodus" in item.property.name:
            self.set_childitem('visu.wintermodus','wintermodus|'+str(self.get_childitem('wartung.wintermodus')))
        
        if ("visu.mow_track" in item.property.name and self.get_childitem('visu.show_mow_track') == True) or ("visu.show_mow_track" in item.property.name and item() == True):
                self._create_mow_track()
        elif "visu.show_mow_track" in item.property.name and item() == False:
            self.set_childitem('visu.svg_mow_track','svg_mow_track|'+str(''))
        
        if "webif.garden_map" in item.property.name:
                self.parse_map()
        
        if "visu.add_svg_images" in item.property.name:
                self.parse_map()
        
        if "visu.mower_colour" in item.property.name:
                self.parse_map()
                
        if item.property.name == self.parent_item+".active_mode.uzsu.schaltuhr":
                myResult = self.items.return_item('indego.active_mode.uzsu.schaltuhr').activate()
                if myResult == True:
                    self.set_childitem('active_mode.uzsu.schaltuhr.active', True)
                    self.set_childitem('active_mode.uzsu.calendar_list',self.parse_uzsu_2_list(item()))
                    self.set_childitem('alm_mode.str','Übersicht mähen nach UZSU:')
                else:                  
                    self.set_childitem('active_mode.uzsu.schaltuhr.active', False)

        if item.property.name == self.parent_item+'.visu.refresh' and item()== True:
            self.set_childitem('update_active_mode', True)
            self._get_calendars()
            self.state()
            self.alert()
            self.device_data()
            self.get_next_time()
            self.get_weather()
            self.load_map()
            self.set_childitem('update_active_mode', False)
            item(False)
                           
    def _send_config(self,url,body=None):
        try:
            myResult, response = self._put_url( url, self.context_id, body)
        except err as Exception:
            self.logger.warning("Error during putting Config {}".format(err))
            return False
        return True

    def send_command(self, item, command=None, caller=None, source=None, dest=None):
        if self.has_iattr(item.conf, 'indego_command'):
            command = json.loads(self.get_iattr_value(item.conf,'indego_command'))
            self.logger.debug("Function Command " + json.dumps(command) + ' ' + str(item()))
            if item():
                message, response = self._put_url(self.indego_url + 'alms/' + self.alm_sn + '/state', self.context_id, command, 10)
                self.logger.debug("Command " + json.dumps(command) + ' gesendet! ' + str(message))
                    
    def _create_mow_track(self):
        if self.get_childitem('visu.model_type') == 2:
            mystroke     ='#C3FECE'
            mystrokewidth ='17'
        else:
            mystroke      ='#999999'
            mystrokewidth ='5'
        myMowTrack = {'Points':self.get_childitem('visu.mow_track'),
                      'style':'fill:none; stroke:'+mystroke+ '; stroke-width: '+mystrokewidth+'; stroke-linecap:round; stroke-linejoin: round;'}
        self.set_childitem('visu.svg_mow_track','svg_mow_track|'+json.dumps(myMowTrack))
        
    def _daystring(self, zeitwert, ausgang):
        if ausgang == 'min':
            zeitwert = zeitwert / 60 / 24
        if ausgang == 'std':
            zeitwert = zeitwert / 24
        tage, std = divmod(zeitwert, 1)
        tage = int(tage)
        std = std * 24
        std, min = divmod(std,1)
        std = int(std)
        min = round(min * 60)
        dayout = str(tage)+' Tage '+str(std)+' Std '+str(min)+' Min'
        return dayout
    
    def _del_message_in_dict(self, myDict, myKey):
        del myDict[myKey]
        
    def _set_read_essages(self):
        msg2setread = self.get_childitem('visu.alerts_set_read')
        myReadMsg = self.get_childitem('visu.alerts')
        
        for message in msg2setread:
            myResult, response = self._put_url(self.indego_url +'alerts/{}'.format(message), self.context_id, None, 10)
            myReadMsg[message]['read_status'] = 'read'
            
        self.set_childitem('visu.alerts', myReadMsg)
        
        
    def _set_clear_message(self):
        msg2clear = self.get_childitem('visu.alerts_set_clear')
        myClearMsg = self.get_childitem('visu.alerts')
        
        for message in msg2clear:
            myResult = self._delete_url(self.indego_url +'alerts/{}'.format(message), self.context_id, 10,auth=(self.user,self.password))
            self._del_message_in_dict(myClearMsg, message)
            
        self.set_childitem('visu.alerts', myClearMsg)
        if (len(myClearMsg)) == 0:
            {
                self.set_childitem('visu.alert_new', False)
            } 
    
    def _check_login_state(self):
        if self.logged_in == False:
            return
        actTimeStamp = time.time()
        if self.expiration_timestamp < actTimeStamp+600:
            self._delete_auth()
            self._auth()
            self.logged_in = self._check_auth()
            self.set_childitem('online', self.logged_in)
            actDate = datetime.now()
            self.logger.info("refreshed Session-ID at : {}".format(actDate.strftime('Date: %a, %d %b %H:%M:%S %Z %Y')))
        else:
            self.logger.info("Session-ID {} is still valid".format(self.context_id))
            
    def _auto_pred_cal_update(self):
        self.cal_upate_count_pred += 1
        self.cal_pred_update_running = True
        
        actCalendar = self.get_childitem('calendar_predictive_sel_cal')
        # set actual Calendar in Calendar-structure
        myCal = self.get_childitem('calendar_predictive')
        myCal['sel_cal'] = actCalendar
        self.set_childitem('calendar_predictive',myCal)
        
        myResult = self._store_calendar(self.predictive_calendar(),'predictive/calendar')
        
        if self.cal_upate_count_pred <=3:
            if myResult != 200:
                if self.cal_upate_count_pred == 1:
                    self.scheduler_add('auto_pred_cal_update', self._auto_pred_cal_update, cycle=60)
                myMsg = "Mäher konnte nicht erreicht werden "
                myMsg += "nächster Versuch in 60 Sekunden "
                myMsg += "Anzahl Versuche : " + str(self.cal_upate_count_pred)
            else:
                self.cal_pred_update_running = False
                self.cal_upate_count_pred = 0
                self.set_childitem('calendar_predictive_save', False)
                try:
                    self.get_sh().scheduler.remove('auto_pred_cal_update')
                except:
                    pass
                myMsg = "Ausschlusskalender wurde gespeichert"

        else: # Bereits drei Versuche getätigt
            try:
                self.get_sh().scheduler.remove('auto_pred_cal_update')
            except:
                pass
            myMsg = "Ausschlusskalender konnte nach drei Versuchen nicht "
            myMsg += "nicht gespeichert werden. "
            myMsg += "Speichern abgebrochen"
            self.cal_pred_update_running = False
            self.cal_upate_count_pred = 0
            self.set_childitem('calendar_predictive_save', False)
        
        self.set_childitem('calendar_predictive_result',myMsg)

            

    def _auto_mow_cal_update(self):
        self.cal_update_count += 1
        self.cal_update_running = True

        actCalendar = self.get_childitem('calendar_sel_cal')
        # set actual Calendar in Calendar-structure
        myCal = self.get_childitem('calendar')
        myCal['sel_cal'] = actCalendar
        self.set_childitem('calendar',myCal)
        myResult = self._store_calendar(self.calendar(),'calendar')
        if self.cal_update_count <=3:
            if myResult != 200:
                if self.cal_update_count == 1:
                    self.scheduler_add('auto_mow_cal_update', self._auto_mow_cal_update, cycle=60)
                myMsg = "Mäher konnte nicht erreicht werden "
                myMsg += "nächster Versuch in 60 Sekunden "
                myMsg += "Anzahl Versuche : " + str(self.cal_update_count)
            else:
                self.cal_update_running = False
                self.cal_update_count = 0
                self.set_childitem('calendar_save', False)
                try:
                    self.get_sh().scheduler.remove('auto_cal_update')
                except:
                    pass
                myMsg = "Mähkalender wurde gespeichert"
                # Deactivate the UZSU, when saving the calendar, calendar-mode is activated
                # and set the correctmode
                self.set_childitem('active_mode.kalender',True)
                

        else: # Bereits drei Versuche getätigt
            try:
                self.get_sh().scheduler.remove('auto_mow_cal_update')
            except:
                pass
            myMsg = "Mähkalender konnte nach drei Versuchen nicht "
            myMsg += "nicht gespeichert werden. "
            myMsg += "Speichern abgebrochen"
            self.cal_update_running = False
            self.cal_update_count = 0
            self.set_childitem('calendar_save', False)
        
        self.set_childitem('calendar_result',myMsg)
    
    
    def _get_calendars(self):    
        if (self.get_childitem("wartung.wintermodus") == True or self.logged_in == False):
            return
        if (self.get_childitem("alm_mode") == 'smart') and ((self.get_childitem('stateCode') == 513) or (self.get_childitem('stateCode') == 518)):
            return     
        self.smart_mow_settings("read")
        try:
            if not self.cal_update_running:
                # get the mowing calendar
                self.calendar = self.items.return_item(self.parent_item + '.' + 'calendar')
                self.calendar(self.get_calendar(), 'indego')
                calendar_list = self.items.return_item(self.parent_item + '.' + 'calendar_list')
                calendar_list(self.parse_cal_2_list(self.calendar._value,'MOW'),'indego')
                self.act_Calender = self.items.return_item(self.parent_item + '.' + 'calendar_sel_cal')
                self.act_Calender(self.get_active_calendar(self.calendar()),'indego')
            if not self.cal_pred_update_running:
                # get the predictve calendar for smartmowing
                self.predictive_calendar = self.items.return_item(self.parent_item + '.' + 'calendar_predictive')
                self.predictive_calendar(self.get_predictive_calendar(), 'indego')
                predictive_calendar_list = self.items.return_item(self.parent_item + '.' + 'calendar_predictive_list')
                predictive_calendar_list(self.parse_cal_2_list(self.predictive_calendar._value,'PRED'),'indego')
                self.act_pred_Calender = self.items.return_item(self.parent_item + '.' + 'calendar_predictive_sel_cal')
                self.act_pred_Calender(self.get_active_calendar(self.predictive_calendar()),'indego')
        except Exception as e:
            self.logger.warning("Problem fetching Calendars: {0}".format(e))
        
        # Get the scheduled smart-mow-calendar
        if self.get_childitem("alm_mode") == 'smart':
            try:
                schedule = self._get_url(self.indego_url + 'alms/' + self.alm_sn +'/predictive/schedule', self.context_id)

                if schedule == False:
                    return
            except Exception as e:
                self.logger.warning("Problem fetching Calendars: {0}".format(e))
            my_pred_cal = {
                            "cals" : [{
                                        "cal" : 9,
                                        'days' : schedule['exclusion_days']
                                     }]
                          } 
            my_smMow_cal = {
                            "cals" : [{
                                        "cal" : 9,
                                        'days' : schedule['schedule_days']
                                     }]
                          }
            my_pred_list = self.parse_cal_2_list(my_pred_cal, None)
            my_smMow_list = self.parse_cal_2_list(my_smMow_cal, None)
            
            self.set_childitem('visu.smartmow_days',[ my_pred_list,my_smMow_list])
        
    def _log_communication(self, type, url, result):
        myLog = self.get_childitem('webif.communication_protocoll')
        if (myLog == None):
            return
        try:
            if len (myLog) >= 500:
                myLog = myLog[1:500]
        except:
            return
        now = self.shtime.now()
        myLog.append(str(now)[0:19]+' Type: ' + str(type) + ' Result : '+str(result) + ' Url : ' + url)
        self.set_childitem('webif.communication_protocoll', myLog)

    def _fetch_url(self, url, username=None, password=None, timeout=10, body=None):
        try:
            myResult, response = self._post_url(url, self.context_id, body, timeout,auth=(username,password))
        except Exception as e:
            self.logger.warning("Problem fetching {0}: {1}".format(url, e))
            return False
        if myResult == False:
            return False
        
        if response.status_code == 200 or response.status_code == 201:
            content = response.json()
            try:
                expiration_timestamp = int(str(response.cookies._cookies['api.indego.iot.bosch-si.com']['/']).split(',')[11].split('=')[1])
            except:
                pass
        else:
            self.logger.warning("Problem fetching {}: HTTP : {}".format(url,  response.status_code))
            content = False
        
        return content,expiration_timestamp
    
    def get_childitem(self, itemname):
        """
        a shortcut function to get value of an item if it exists
        :param itemname:
        :return:
        """
        item = self.items.return_item(self.parent_item + '.' + itemname)  
        if (item != None):
            return item()
        else:
            self.logger.warning("Could not get item '{}'".format(self.parent_item+'.'+itemname))    
    
    
    def set_childitem(self, itemname, value ):
        """
        a shortcut function to set an item with a given value if it exists
        :param itemname:
        :param value:
        :return:
        """
        item = self.items.return_item(self.parent_item + '.' + itemname)  
        if (item != None): 
            item(value, 'indego')
        else:
            self.logger.warning("Could not set item '{}' to '{}'".format(self.parent_item+'.'+itemname, value))

    
    def _delete_url(self, url, contextid=None, timeout=40, auth=None):
        headers = {
                   'x-im-context-id' : self.context_id
                  }
        response = False
        try:
            response = requests.delete(url, headers=headers, auth=auth)
            self._log_communication('delete', url, response.status_code)
        except Exception as e:
            self.logger.warning("Problem deleting {}: {}".format(url, e))
            return False

        if response.status_code == 200 or response.status_code == 201:
            try:
                content = response
            except:
                content = False
                pass
        else:
            self.logger.warning("Problem deleting {}: HTTP : {}".format(url, response.status_code))
            content = False
        
        return content

        
    def _get_url(self, url, contextid=None, timeout=40, auth=None):
        headers = {
                   'x-im-context-id' : self.context_id
                  }
        response = False
        try:
            if auth == None:
                response = requests.get(url, headers=headers)
            else:
                response = requests.get(url, headers=headers, auth=auth)
            self._log_communication('get   ', url, response.status_code)
        except Exception as e:
            self.logger.warning("Problem fetching {}: {}".format(url, e))
            return False
        
        if response.status_code == 204:                  # No content
                self.logger.info("Got no Content : {}".format(url))
                return False

        elif response.status_code == 200 or response.status_code == 201:
            try:
                if str(response.headers).find("json") > -1:
                    content = response.json()
                elif str(response.headers).find("svg") > -1:
                    content = response.content
                    
            except:
                content = False
                pass
        else:
            self.logger.warning("Problem getting {}: HTTP : {}".format(url, response.status_code))
            content = False
        
        return content
        
    def _post_url(self, url, contextid=None, body=None, timeout=2, auth = ""):
        if (contextid != None and contextid != ""):
            headers = {
                       'x-im-context-id' : self.context_id
                      }
        else:
            headers = ""
        
        response = False
        try:
            if body == None:
                response = requests.post(url, headers=headers, auth=auth)
            else:
                response = requests.post(url, headers=headers ,json=body, auth=auth)
            self._log_communication('post  ', url, response.status_code)
        except Exception as e:
            self.logger.warning("Problem posting {}: {}".format(url, e))
            return False
        self.logger.debug('post gesendet an URL: {} context-ID: {} json : {}'.format(url,self.context_id,json.dumps(body)))
        
        if response.status_code == 200:
            self.logger.info("Set correct post for {}".format(url))
            return True,response
        else:
            self.logger.info("Error during post for {} HTTP-Status :{}".format(url, response.status_code))
            return False,response
            
    
    
    def _put_url(self, url, contextid=None, body=None, timeout=2):
        headers = {
                   'x-im-context-id' : contextid
                  }
        
        response = False
        try:
            response = requests.put(url, headers=headers, json=body)
            self._log_communication('put   ', url, response.status_code)
        except Exception as e:
            self.logger.warning("Problem putting {}: {}".format(url, e))
            self._log_communication('put   ', url, response.status_code)
            return False, response
        self.logger.debug('put gesendet an URL: {} context-ID: {} json : {}'.format(url,self.context_id,json.dumps(body)))
        
        if response.status_code == 200:
            self.logger.info("Set correct put for {}".format(url))
            return True, response
        else:
            self.logger.info("Error during put for {} HTTP-Status :{}".format(url, response.status_code))
            return False, response

    def _set_smart(self, enable=None):

        if enable:
            self.logger.debug("SMART-Mow-Modus aktivieren")
            command = {"enabled": True}
        else:
            self.logger.debug("SMART-Mow-Modus deaktivieren")
            command = {"enabled": False}
        result, response = self._put_url(self.indego_url + 'alms/' + self.alm_sn + '/predictive', self.context_id, command, 10)
        self.logger.debug("Smart Command " + json.dumps(command) + ' gesendet! Result :' + str(result))


    def _check_state_4_protocoll(self):
        myActState = self.get_childitem("stateCode")
        if myActState == 772 or myActState == 775 or myActState == 769 or myActState == 770 or myActState == 771 or myActState == 773 or myActState == 774 or myActState == 257 or myActState == 260 or myActState == 261 or myActState == 262 or myActState == 263:                           # 769 = fährt zur Station / 772 = Mähzeit beendet / 775 = fertig gemäht
            self.get_sh().scheduler.change('plugins.indego.state', cycle={self.cycle:None})
            self.set_childitem("laststateCode", myActState)
            self.position_detection = False
        
        
    def _delete_auth(self):
        '''
        DELETE https://api.indego.iot.bosch-si.com/api/v1/authenticate
        x-im-context-id: {contextId}
        '''
        headers = {'Content-Type': 'application/json',
                   'Accept' : 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                   'x-im-context-id' : self.context_id
                  }
        url = self.indego_url + 'authenticate'
        try:
            response = self._delete_url(url, self.context_id, 10, auth=(self.user,self.password))
        except Exception as e:
            self.logger.warning("Problem logging off {0}: {1}".format(url, e))
            return False
        if response == False:
            return False
        
        if (response.status_code == 200 or response.status_code == 201): 
            self.logger.info("Your logged off successfully")
            return True
        else:
            self.logger.info("Log off was not successfull : {0}".format(response.status_code))
            return False

    def _store_calendar(self, myCal = None, myName = ""):
        '''
        PUT https://api.indego.iot.bosch-si.com/api/v1/alms/{serial}/calendar
        x-im-context-id: {contextId}
        '''
        url = "{}alms/{}/{}".format( self.indego_url, self.alm_sn, myName)
        
        try:
            myResult, response = self._put_url( url, self.context_id, myCal)
        except err as Exception:
            self.logger.warning("Error during saving Calendar-Infos Error {}".format(err))
            return None
            
        if response.status_code == 200:
            self.logger.info("Set correct Calendar settings for {}".format(myName))
        else:
            self.logger.info("Error during saving Calendar settings for {} HTTP-Status :{}".format(myName, response.status_code))

        return response.status_code            

        
    
    def _check_auth(self):
        '''
        GET https://api.indego.iot.bosch-si.com/api/v1/authenticate/check
        Authorization: Basic bWF4Lm11c3RlckBhbnl3aGVyZS5jb206c3VwZXJzZWNyZXQ=
        x-im-context-id: {contextId}
        '''
        headers = {'Content-Type': 'application/json',
                   'Accept' : 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                   'x-im-context-id' : self.context_id
                  }
        url = self.indego_url + 'authenticate/check'
        
        try:
            response = self._get_url(url, self.context_id, 10, auth=(self.user,self.password))
            #response = requests.get(url,auth=(self.user,self.password), headers=headers)
            
            
        except Exception as e:
            self.logger.warning("Problem checking Authentication {0}: {1}".format(url, e))
            return False

        if response != False:
            self.logger.info("Your are still logged in to the Bosch-Web-API")
            return True
        else:
            self.logger.info("Your are not logged in to the Bosch-Web-API")
            return False

        
        
    def _auth(self):
        url = self.indego_url + 'authenticate'
        auth_response,expiration_timestamp = self._fetch_url(url, self.user, self.password, 10,{"device":"","os_type":"Android","os_version":"4.0","dvc_manuf":"unknown","dvc_type":"unknown"})
        if auth_response == False:
            self.logger.error('AUTHENTICATION INDEGO FAILED! Plugin not working now.')
        else:
            self.last_login_timestamp = datetime.timestamp(datetime.now())
            self.expiration_timestamp = expiration_timestamp
            self.logger.debug("String Auth: " + str(auth_response))
            self.context_id = auth_response['contextId']
            self.logger.info("context ID received :{}".format(self.context_id))
            self.user_id = auth_response['userId']
            self.logger.info("User ID received :{}".format(self.user_id))
            self.alm_sn = auth_response['alm_sn']
            self.logger.info("Serial received : {}".format(self.alm_sn))
    
    def get_predictive_calendar(self):
        '''
        GET
        https://api.indego.iot.bosch-si.com/api/v1/alms/{serial}/predictive/calendar
        x-im-context-id: {contextId}
        '''
        if (self.get_childitem("alm_mode") == 'smart') and ((self.get_childitem('stateCode') == 513) or (self.get_childitem('stateCode') == 518)):
            return        
        url = "{}alms/{}/predictive/calendar".format( self.indego_url, self.alm_sn)
        
        headers = {
                   'x-im-context-id' : self.context_id
                  }

        try:
            response = self._get_url(url, self.context_id, 10)
            #response = requests.get(url, headers=headers)
        except err as Exception:
            self.logger.warning("Error during getting predictive Calendar-Infos")
            return None
            
        if response != False:
            self.logger.info("Got correct predictive Calendar settings for smartmowing")
            return response

    
    def get_calendar(self):
        '''
        GET
        https://api.indego.iot.bosch-si.com/api/v1/alms/{serial}/calendar
        x-im-context-id: {contextId}
        '''
        url = "{}alms/{}/calendar".format( self.indego_url, self.alm_sn)
        headers = {
                   'x-im-context-id' : self.context_id
                  }

        try:
            response = self._get_url(url, self.context_id, 10)
            #response = requests.get(url, headers=headers)
        except err as Exception:
            self.logger.warning("Error during getting Calendar-Infos")
            return None
            
        if response != False:
            self.logger.info("Got correct Calendar settings for mowing")
            return response
    
    def clear_calendar(self, myCal = None):
        for cal_item in myCal['cals']:
            myCalendarNo = cal_item['cal']
            for days in cal_item['days']:
                myDay = days['day']
                for slots in days['slots']:
                    slots['En'] = False
                    slots['StHr'] = "00"
                    slots['StMin'] = "00"
                    slots['EnHr'] = "00"
                    slots['EnMin'] = "00"

        return myCal
    
            
    def build_new_calendar(self, myList = None,type = None):
        if (type =='MOW'):
            selected_calendar = self.get_childitem('calendar_sel_cal')
        else:
            selected_calendar = self.get_childitem('calendar_predictive_sel_cal')
        newCal = {}
        emptySlot = {
                    'StHr' : '00',
                    'StMin' : '00',
                    'EnHr' : '00',
                    'EnMin' : '00',
                    'En' : False
                    }
        newCal['sel_cal'] = selected_calendar
        newCal['cals'] = []
        newCal['cals'].append({'cal':selected_calendar})  #['cal'] = selected_calendar
        newCal['cals'][0]['days'] = []
    
        for myKey in myList:
            if (myKey == "Params"):
                continue
            NewEntry = {}
            Start = ""
            End = ""
            Days  = ""
            myCalNo = 0
            calEntry = myList[myKey].items()
    
            for myEntry in  calEntry:
                if (myEntry[0] =='Start'):
                    Start = myEntry[1]
                elif (myEntry[0] == 'End'):
                    End = myEntry[1]
                elif (myEntry[0] == 'Days'):
                    Days = myEntry[1]
                elif (myEntry[0] == 'Key'):
                    myCalNo = int(myEntry[1][0:1])
            if (myCalNo != 1 and type =='PRED') or (myCalNo != 2 and type =='MOW'):
                continue
            for day in Days.split((',')):
                newSlot = {
                            'StHr' : Start[0:2],
                            'StMin' : Start[3:5],
                            'EnHr' : End[0:2],
                            'EnMin' : End[3:5],
                            'En' : True
                           }
                newDay = {
                            'slots': [newSlot],
                            'day' : int(day)
                         }
                dayFound = False
                for x in newCal['cals'][0]['days']:
                    if x['day'] == int(day):
                        oldSlot = x['slots']
                        x['slots'].append(newSlot)
                        dayFound = True
                        break
                if not dayFound:
                    newCal['cals'][0]['days'].append(newDay)
        # Add the empty slots for mowing calendars
        final_Cal = newCal
        calCounter = 0
        for calEntry in newCal['cals']:
            if calEntry['cal'] != 2:
                calCounter += 1
                continue
            dayCounter = 0
            for days in calEntry['days']:
                if len(days['slots']) < 2:
                       # add a empty slot
                       final_Cal['cals'][calCounter]['days'][dayCounter]['slots'].append(emptySlot)
                dayCounter += 1

        return final_Cal
        
    
    def create_empty_calendar(self,needed_cals=None):
        needed_cals=[2,3]
        newCal = {'cals':[]}
        emptySlot = {
                    'StHr' : '00',
                    'StMin' : '00',
                    'EnHr' : '00',
                    'EnMin' : '00',
                    'En' : False
                    }
    
        days=[]
        #Create a complete week
        dayCount = 0
        while dayCount <= 6:
            newDay = {
                     'slots': [emptySlot,emptySlot],
                     'day' : int(dayCount)
                     }
            days.append(newDay)
            dayCount +=1
    
        newCal['sel_cal'] = 2
        for cal in needed_cals:
            newCalEntry={'days':days}
            newCalEntry['cal']=cal
            newCal['cals'].append(newCalEntry)
    
        print (json.dumps(newCal))
    
    
                
    def parse_list_2_cal(self,myList = None, myCal = None,type = None):
        if (type == 'MOW' and len(self.calendar_count_mow) == 5):
            self.clear_calendar(myCal._value)

        if (type == 'PRED' and len(self.calendar_count_pred) == 5):
            self.clear_calendar(myCal._value)
                
        if (type == 'MOW' and len(self.calendar_count_mow) < 5):
            myCal._value = self.build_new_calendar(myList,type)
        
        elif (type == 'PRED' and len(self.calendar_count_pred) < 5):
            myCal._value = self.build_new_calendar(myList,type)
        
        else:
            self.clear_calendar(myCal._value)
            for myKey in myList:
                if (myKey == "Params"):
                    continue
                Start = ""
                End = ""
                Days  = ""
                myCalNo = 0
                calEntry = myList[myKey].items()
                for myEntry in  calEntry:
                    if (myEntry[0] =='Start'):
                        Start = myEntry[1]
                    elif (myEntry[0] == 'End'):
                        End = myEntry[1]
                    elif (myEntry[0] == 'Days'):
                        Days = myEntry[1]
                    elif (myEntry[0] == 'Key'):
                        myCalNo = int(myEntry[1][0:1])-1
                # Now Fill the Entry in the Calendar
                for day in Days.split((',')):
                    if (myCal._value['cals'][myCalNo]['days'][int(day)]['slots'][0]['En'] == True):
                        actSlot = 1
                    else:
                        actSlot = 0
                    myCal._value['cals'][myCalNo]['days'][int(day)]['slots'][actSlot]['StHr'] = Start[0:2]
                    myCal._value['cals'][myCalNo]['days'][int(day)]['slots'][actSlot]['StMin'] = Start[3:5]
                    myCal._value['cals'][myCalNo]['days'][int(day)]['slots'][actSlot]['EnHr'] = End[0:2]
                    myCal._value['cals'][myCalNo]['days'][int(day)]['slots'][actSlot]['EnMin'] = End[3:5]
                    myCal._value['cals'][myCalNo]['days'][int(day)]['slots'][actSlot]['En'] = True  

        self.logger.info("Calendar was updated Name :'{}'".format(myCal._name))
    
    def get_active_calendar(self, myCal = None):    
        # First get active Calendar
        activeCal = myCal['sel_cal']
        return activeCal
    
    def parse_uzsu_2_list(self, uzsu_dict=None):
        weekDays = {'MO' : "0" ,'TU' : "1" ,'WE' : "2" ,'TH' : "3",'FR' : "4",'SA' : "5" ,'SU' : "6" }
        myCal = {}
        
        for myItem in uzsu_dict['list']:
            # First run get all the start times
            myDays = myItem['rrule'].split(';')[1].split("=")[1].split(",")
            if myItem['value'] == '10' and myItem['active'] == True:
                if "sun" in myItem['time']:
                    if not 'calculated' in myItem:
                        continue
                    else:
                        myItem['time']=myItem['calculated']
                myKey = "8-"+myItem['time']
                if not myKey in myCal:
                    myCal[myKey] = {'Days':'', 'Start':'','End':'','Key':'','Color' : '#0AFF0A'}
                    start_hour = float(myItem['time'].split(':')[0])
                    myCal[myKey]['Start']=str("%02d" % start_hour)+':'+myItem['time'].split(':')[1]
                    #myCal[myKey]['Start'] = myItem['time']
                    calDays =""
                else:
                    calDays = myCal[myKey]['Days']
    
                for day in myDays:
                    calDays += ","+ weekDays[day]
                if calDays[0:1] == ",":
                    calDays = calDays[1:]
                myCal[myKey]['Days'] = calDays
            # Second run get all the stop times
        for myItem in uzsu_dict['list']:
            myDays = myItem['rrule'].split(';')[1].split("=")[1].split(",")
            if myItem['value'] == '20' and myItem['active'] == True:
                if "sun" in myItem['time']:
                    if not 'calculated' in myItem:
                        continue
                    else:
                        myItem['time']=myItem['calculated']
                for myCalEntry in myCal:
                    for day in myDays:
                        if weekDays[day] in myCal[myCalEntry]['Days']:
                            myCal[myCalEntry]['End'] = myItem['time']
                            myCal[myCalEntry]['Key'] = myCalEntry+'-'+ myItem['time']
        # finally build the calendar
        final_Calender = {}
        for myCalEntry in myCal:
            if myCal[myCalEntry]['End'] == "":
                start_hour = myCal[myCalEntry]['Start'].split(':')[0]
                stop_hour = float(start_hour)+4
                if stop_hour > 23:
                    stop_hour = 23
                    
                myCal[myCalEntry]['Color']='#FFA985'    
                myCal[myCalEntry]['End']=str("%02d" % stop_hour)+':'+myCal[myCalEntry]['Start'].split(':')[1]
                myCal[myCalEntry]['Key']='8-'+myCal[myCalEntry]['Start']+'-'+myCal[myCalEntry]['End']
            final_Calender[myCal[myCalEntry]['Key']]=myCal[myCalEntry]
        if len(final_Calender) > 0:
            final_Calender['Params']={'CalCount': [8]}
        else:
            final_Calender['Params']={'CalCount': [8]}
        return final_Calender
    
    
    
    def parse_cal_2_list(self, myCal = None, type=None):
        myList = {}
        myList['Params']={}
        myCalList = []
        for cal_item in myCal['cals']:
            print (cal_item)
            myCalendarNo = cal_item['cal']
            if not(myCalendarNo in myCalList):
                myCalList.append(int(myCalendarNo))
            for days in cal_item['days']:
                myDay = days['day']
                print (days)
                for slots in days['slots']:
                    print (slots)
                    #for slot in slots:
                    myEnabled = slots['En']
                    if (myEnabled):
                        try:
                            myStartTime1 = str('%0.2d' %slots['StHr'])+':'+str('%0.2d' %slots['StMin'])
                        except Exception as err:
    
                            myStartTime1 = '00:00'
                        try:
                            myEndTime1 = str('%0.2d' %slots['EnHr'])+':'+str('%0.2d' %slots['EnMin'])
                        except:
                            myEndTime1 = '00:00'
                        myKey = str(myCalendarNo)+'-'+myStartTime1+'-'+myEndTime1
                        myDict = {
                                    'Key':myKey,
                                    'Start' : myStartTime1,
                                    'End'   : myEndTime1,
                                    'Days'  : str(myDay)
                                 }
                        if 'Attr' in slots:
                            if slots['Attr'] == "C":    # manual Exclusion Time
                                mycolour = '#DC143C'
                            elif slots['Attr'] == "p":  # Rain
                                mycolour = '#BEBEBE'
                            elif slots['Attr'] == "P":  # Heavy Rain
                                mycolour = '#BEBEBE'
                            elif slots['Attr'] == "D":
                                mycolour = '#BEBEBE'    # dont know ??
                            else:
                                mycolour = '#BEBEBE'    # Heat ??
                            myDict['Color']= mycolour
                            
                        if not myKey in str(myList):
                            myList[myKey] = myDict
    
                        else:
                            if (myStartTime1 != '00:00:' and myEndTime1 != '00:00'):
                                myList[myKey]['Days'] = myList[myKey]['Days']+','+str(myDay)

        myList['Params']['CalCount'] = myCalList
        if (type == 'MOW'):
            self.calendar_count_mow = myCalList
        elif (type == 'PRED'):
            self.calendar_count_pred = myCalList
        
        return myList
    
    
    def parse_dict_2_item(self,myDict, keyEntry):
        for m in myDict:
            if type(myDict[m]) != dict:
                self.set_childitem(keyEntry+m, myDict[m])
            else:
                self.parse_dict_2_item(myDict[m],keyEntry+m+'.')
                
                
    def get_location(self):
        url = "{}alms/{}/predictive/location".format( self.indego_url, self.alm_sn)
        try:
            location = self._get_url( url, self.context_id, 20)    
        except Exception as e:
            self.logger.warning("Problem fetching {}: {}".format(url, e))
            return false
        if location != False:
            self.set_childitem('location', location)
            if "latitude" in location:
                self.set_childitem('location.latitude', location["latitude"])
            if "longitude" in location:
                self.set_childitem('location.longitude', location["longitude"])
            if "timezone" in location:
                self.set_childitem('location.timezone', location["timezone"])
            return True
        else:
            return False 
    
    def smart_mow_settings(self, mode =""):
        # get SmartMowSetup
        url = "{}alms/{}/predictive/setup".format( self.indego_url, self.alm_sn)
        if (mode == 'read'):
            try:
                predictiveSetup = self._get_url( url, self.context_id, 10)    
            except Exception as e:
                self.logger.warning("Problem fetching {}: {}".format(url, e))
            if predictiveSetup != False:
                self.set_childitem('smartmowsetup', predictiveSetup)
            else:       # create empty dict
                self.set_childitem('smartmowsetup',{
                                                      "full_cuts": 2,
                                                      "no_mow_calendar_days": [],
                                                      "avoid_rain": False,
                                                      "use_grass_growth": False,
                                                      "avoid_temperature": False,
                                                    })
                
            predictiveSetup = self.get_childitem('smartmowsetup')
            try:
                self.set_childitem('visu.avoid_temperature',predictiveSetup['avoid_temperature'] )
            except:
                self.set_childitem('visu.avoid_temperature',False)
            try:
                self.set_childitem('visu.avoid_rain',predictiveSetup['avoid_rain'] )
            except:
                self.set_childitem('visu.avoid_rain',False)
            try:
                self.set_childitem('visu.use_grass_growth',predictiveSetup['use_grass_growth'])
            except:
                self.set_childitem('visu.use_grass_growth',False)
            try:
                self.set_childitem('visu.full_cuts',predictiveSetup['full_cuts'] )
            except:
                self.set_childitem('visu.full_cuts',2 )
            
        if (mode == "write"):
            predictiveSetup = {   "full_cuts": 2,
                                  "no_mow_calendar_days": [],
                                  "avoid_rain": False,
                                  "use_grass_growth": False,
                                  "avoid_temperature": False,
                               }
            predictiveSetup['avoid_temperature'] = self.get_childitem('visu.avoid_temperature')
            predictiveSetup['avoid_rain'] = self.get_childitem('visu.avoid_rain')
            predictiveSetup['use_grass_growth'] = self.get_childitem('visu.use_grass_growth')
            predictiveSetup['full_cuts'] = self.get_childitem('visu.full_cuts')
            if (self.get_childitem('visu.use_exclude_time_4_sms') == True):
                predictiveSetup['no_mow_calendar_days'] = self.get_childitem('calendar_predictive')['cals'][0]['days']
            else:
                predictiveSetup['no_mow_calendar_days']=[]
            
            try:
                myResult, response = self._put_url( url, self.context_id, predictiveSetup)    
            except Exception as e:
                self.logger.warning("Problem putting {}: {}".format(url, e))
    
    
    def get_alm_config(self):
        '''
        @GET("alms/{alm_serial}/config")")
        '''
        activeModel = self.get_childitem('visu.model_type')
        if activeModel != 2:
            return
        
        url = "{}alms/{}/config".format( self.indego_url, self.alm_sn)
        try:
            alm_config = self._get_url( url, self.context_id, 20)    
        except Exception as e:
            self.logger.warning("Problem getting {}: {}".format(url, e))
        
        if alm_config != False:
            self.set_childitem('wartung.alm_config', alm_config)
    
    def start_manual_update(self):
        '''
        @PUT("alms/{alm_serial}/updates")
        '''
        url = '{}alms/{}/updates'.format( self.indego_url, self.alm_sn)
        myResult, response = self._put_url(url, self.context_id, None, 10)
        
           
    def get_automatic_updates(self):
        '''
        @GET("alms/{alm_serial}/automaticUpdate")
        '''
        url = '{}alms/{}/automaticUpdate'.format( self.indego_url, self.alm_sn)
        automatic_updates = self._get_url( url, self.context_id, 20)
        if automatic_updates != False:
            self.set_childitem('wartung.update_auto', automatic_updates['allow_automatic_update'])
        
        
        
    def set_automatic_updates(self):
        '''
        @PUT("alms/{alm_serial}/automaticUpdate")
        '''
        body = {"allow_automatic_update": self.get_childitem('wartung.update_auto')}
        url = '{}alms/{}/automaticUpdate'.format( self.indego_url, self.alm_sn)
        myResult, response = self._put_url(url, self.context_id, body, 10)
        
        
    def check_update(self):
        '''
        @GET("alms/{alm_serial}/updates")
        '''
        url = "{}alms/{}/updates".format( self.indego_url, self.alm_sn)
        try:
            available_updates = self._get_url( url, self.context_id, 20)    
        except Exception as e:
            self.logger.warning("Problem getting {}: {}".format(url, e))
        if available_updates != False:
            if (available_updates['available']) == True:
                self.set_childitem('wartung.update','JA')
            else:
                self.set_childitem('wartung.update','NEIN')
                
                
    def get_operating_data(self):
        '''
        @GET("alms/{alm_serial}/operatingData")
        '''
        if (self.get_childitem("wartung.wintermodus") == True or self.logged_in == False):
            return
            
        url = "{}alms/{}/operatingData".format( self.indego_url, self.alm_sn)
        try:
            operating_data = self._get_url( url, self.context_id, 20)    
        except Exception as e:
            self.logger.warning("Problem getting {}: {}".format(url, e))
        if operating_data != False:
            self.parse_dict_2_item(operating_data,'operatingInfo.')
        # Set Visu-Items
        activeModel = self.get_childitem('visu.model_type')
        if (activeModel == 1):      # the big ones
            try:
                myBatteryVoltage = self.get_childitem('operatingInfo.battery.voltage')
                if myBatteryVoltage > 35.0:
                    myBatteryVoltage = 35.0
                myVoltage = myBatteryVoltage - 30.0
                myLoad_percent = myVoltage/5.0 * 100.0
                self.set_childitem('visu.battery_load', myLoad_percent)
                myLoad_icon = myVoltage/5.0*255.0
                self.set_childitem('visu.battery_load_icon', myLoad_icon)
            except err as Exception:
                self.logger.warning("Problem to calculate Battery load")
        elif (activeModel == 2):    # the small ones
            try:
                myLoad_percent = self.get_childitem('operatingInfo.battery.percent')
                self.set_childitem('visu.battery_load', myLoad_percent)
                myLoad_icon = myLoad_percent/100.0*255.0
                self.set_childitem('visu.battery_load_icon', myLoad_icon)
            except err as Exception:
                self.logger.warning("Problem to calculate Battery load")
        else:
            pass
    

        
        # Get Network-Info - only for the 350/400er
        myType = self.get_childitem('visu.model_type')
        if (myType == 2):
            url = "{}alms/{}/network".format( self.indego_url, self.alm_sn)
            try:
                network_data = self._get_url( url, self.context_id, 20)    
            except Exception as e:
                self.logger.warning("Problem fetching {}: {}".format(url, e))
            if network_data != False:
                try:
                    self.parse_dict_2_item(network_data,'network.')
                except err as Exception:
                    self.logger.warning("Problem parsing Network-Info : {}".format(err))
            Providers = {
                        "26217"  :"E-Plus",
                        "26210"  :"DB Netz AG",
                        "26205"  :"E-Plus",
                        "26277"  :"E-Plus",
                        "26203"  :"E-Plus",
                        "26212"  :"E-Plus",
                        "26220"  :"E-Plus",
                        "26214"  :"Group 3G UMTS",
                        "26243"  :"Lycamobile",
                        "26213"  :"Mobilcom",
                        "26208"  :"O2",
                        "26211"  :"O2",
                        "26207"  :"O2",
                        "26206"  :"T-mobile/Telekom",
                        "26201"  :"T-mobile/Telekom",
                        "26216"  :"Telogic/ViStream",
                        "26202"  :"Vodafone D2",
                        "26242"  :"Vodafone D2",
                        "26209"  :"Vodafone D2",
                        "26204"  :"Vodafone D2"
                        }
            myMcc = self.get_childitem('network.mcc')
            myMnc = self.get_childitem('network.mnc')
            try:
                actProvider = Providers[str(myMcc)+str('%0.2d' %myMnc)]
            except:
                actProvider = 'unknown('+str(myMcc)+str('%0.2d' %myMnc)+')'
                
            self.set_childitem('visu.network.act_provider', actProvider)
            ProviderLst = self.get_childitem('network.networks')
            myLst = ""
            for entry in ProviderLst:
                myLst += Providers[str(entry)]+', '
                
            self.set_childitem('visu.network.available_provider', myLst[0:-2])
             
                           
    
    def get_next_time(self):
        if (self.get_childitem("wartung.wintermodus") == True or self.logged_in == False):
            return        
        # get the next mowing time
        url = "{}alms/{}/predictive/nextcutting?last=YYYY-MM-DD-HH:MM:SS%2BHH:MM".format( self.indego_url, self.alm_sn)

        try:
            next_time = self._get_url( url, self.context_id, 10)
        except Exception as e:
            next_time = False
            self.logger.warning("Problem fetching {0}: {1}".format(url, e))        
        if next_time == False:
            self.set_childitem('next_time','nicht geplant')
            self.logger.info("Got next-time - nothing scheduled")
        else:
            try:
                
                self.logger.debug("Next time raw : {}".format(json.dumps(next_time))) # net_time was here
                new_time = next_time['mow_next']
                new_time = new_time.replace(':', '')
                    
                time_text  = new_time[8:10] + '.'
                time_text += new_time[5:7] + '.'
                time_text += new_time[0:4] + ' - '
                time_text += new_time[11:13] + ':'
                time_text += new_time[13:15]
                next_time = str(time_text)

                self.logger.debug("Next time final : {}".format(next_time))
                self.set_childitem('next_time',next_time)
            except Exception as e:
                self.set_childitem('next_time','kein Mähen geplant')
                self.logger.warning("Problem to decode {0} in function get_next_time(): {1}".format(next_time, e))
                
        # get the last mowing time
        url = "{}alms/{}/predictive/lastcutting".format( self.indego_url, self.alm_sn)
        try:
            last_time = self._get_url( url, self.context_id, 10)
        except Exception as e:
            last_time = False
            self.logger.warning("Problem fetching {0}: {1}".format(url, e))        
        if last_time == False:
            self.set_childitem('last_time','kein letztes Mähen bekannt')
            self.logger.info("Got last-time - nothing stored")
        else:
            try:
                
                self.logger.debug("Last time raw : {}".format(json.dumps(last_time))) # net_time was here
                new_time = last_time['last_mowed']
                new_time = new_time.replace(':', '')
                    
                time_text  = new_time[8:10] + '.'
                time_text += new_time[5:7] + '.'
                time_text += new_time[0:4] + ' - '
                time_text += new_time[11:13] + ':'
                time_text += new_time[13:15]
                last_time = str(time_text)

                self.logger.debug("Next time final : {}".format(next_time))
                self.set_childitem('last_time',last_time)
            except Exception as e:
                self.set_childitem('last_time','kein letztes Mähen bekannt')
                self.logger.warning("Problem to decode {0} in function get_next_time(): {1}".format(next_time, e))

                
    def get_weather(self):
        if self.logged_in == False:
            return
        try:
            weather = self._get_url(self.indego_url +'alms/'+ self.alm_sn +'/predictive/weather',self.context_id,10)
        except err as Exception:
            return 
        if weather == False:
            return
        myDummy = self.get_childitem("weather_pics")
        myPictures = json.loads(myDummy)
        for i in weather['LocationWeather']['forecast']['intervals']:
            position = str(weather['LocationWeather']['forecast']['intervals'].index(i))
            self.logger.debug("POSITION :".format(position))
            for x in i:
                wertpunkt = x
                wert = str(i[x])
                self.logger.debug('ITEM indego.weather.int_{} - Wert {}:'.format(position,wertpunkt))
                if wertpunkt == 'dateTime':
                    self.logger.debug("DATE__TIME :{}".format(wert))
                    wert= datetime.strptime(wert,'%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=self.shtime.tzinfo())
                if wertpunkt == 'wwsymbol_mg2008':
                    try:
                        self.set_childitem('weather.int_'+position+'.'+'picture',self.path_2_weather_pics+myPictures[wert])
                    except:
                        # got known Weather-Symbol
                        self.logger.warning("Got unknown Value for Weather-Pic, Value: {}".format(str(wert)))
                        self.set_childitem('weather.int_'+position+'.'+'picture',self.path_2_weather_pics+'na.png')
                    self.logger.debug("WERTPUNKT : {}".format(wertpunkt))
                self.set_childitem('weather.int_'+position+'.'+wertpunkt,wert)

        for i in weather['LocationWeather']['forecast']['days']:
            position_day = str(weather['LocationWeather']['forecast']['days'].index(i))
            self.logger.debug("POSITION_day :".format(position_day))
            for x in i:
                wertpunkt_day = x
                wert_day = str(i[x])
                self.logger.debug('ITEM DAY indego.weather.day_{} : {}'.format(position_day,wertpunkt_day))
                if wertpunkt_day == 'date':
                    wert_day = datetime.strptime(wert_day,'%Y-%m-%d').replace(tzinfo=self.shtime.tzinfo())
                    days = ["Montag","Dienstag","Mittwoch","Donnerstag","Freitag","Samstag","Sonntag"]
                    dayNumber = wert_day.weekday()
                    wochentag = days[dayNumber]
                    self.set_childitem('weather.day_'+position_day+'.'+'wochentag',wochentag)
                else:
                    self.set_childitem('weather.day_'+position_day+'.'+wertpunkt_day,wert_day)

    def alert(self):
        if (self.get_childitem("wartung.wintermodus") == True or self.logged_in == False):
            return
        alert_response = self._get_url(self.indego_url + 'alerts', self.context_id, 10)
        if alert_response == False:
            self.logger.debug("No Alert or error")
            self.alert_reset = False
        else:
            if len(alert_response) == 0:
                self.logger.debug("No new Alert Messages")

            else:
                actAlerts = self.get_childitem('visu.alerts')
                for myAlert in alert_response:
                    if not (myAlert['alert_id'] in actAlerts):
                        # add new alert to dict
                        self.logger.debug("Got new Alarm : {} - {} ".format(myAlert['alert_id'], myAlert['message']))
                        myAlert['message'].replace(' Bitte folgen Sie den Anweisungen im Display des Mähers.', '')
                        actAlerts[myAlert['alert_id']]=myAlert
                        self.set_childitem('visu.alert_new', True)
                        self.check_alarm_triggers(myAlert['message']+' '+myAlert['headline'])
                
                self.set_childitem('visu.alerts', actAlerts)

    def alert_delete(self, alert_id):
        self.logger.debug("deleting alert_id " + str(alert_id))
        result = self._delete_url(self.indego_url + 'alerts/' + alert_id, self.context_id, 50,auth=(username,password))

    def device_data(self):
        if (self.get_childitem("wartung.wintermodus") == True or self.logged_in == False):
            return        
        
        # Get Location
        self.get_location()
        # CheckUpdates
        self.check_update()
        # Get ALM-Config
        self.get_alm_config()
        # Get Auto-Updates enabled
        self.get_automatic_updates()
        
        self.logger.debug('getting device_date')
        device_data_response = self._get_url(self.indego_url + 'alms/' + self.alm_sn, self.context_id)
        if device_data_response == False:
            self.logger.error('Device Data disconnected')
        else:
            self.logger.debug('device date JSON: {} '.format(json.dumps(device_data_response)))

            alm_sn = device_data_response['alm_sn']
            self.set_childitem('alm_sn',alm_sn)
            self.logger.debug("alm_sn :".format(alm_sn))

            if 'alm_name' in device_data_response:
                alm_name = device_data_response['alm_name']
                self.set_childitem('alm_name',alm_name)
                self.logger.debug("alm_name " + str(alm_name))

            service_counter = device_data_response['service_counter']
            self.set_childitem('service_counter',service_counter)
            self.logger.debug("service_counter :".format(service_counter))
            service_counter = self._daystring(service_counter, 'min')
            self.set_childitem('service_counter.dhm',service_counter)

            needs_service = device_data_response['needs_service']
            self.set_childitem('needs_service',needs_service)
            self.logger.debug("needs_service : {}".format(needs_service))

            alm_mode = device_data_response['alm_mode']
            self.set_childitem('alm_mode',alm_mode)
            if alm_mode == 'smart':
                self.set_childitem('SMART', True)
            else:
                self.set_childitem('SMART', False)
                
            if alm_mode == 'smart':
                self.set_childitem('alm_mode.str','Übersicht SmartMow mähen:')
            elif alm_mode == 'calendar':
                self.set_childitem('alm_mode.str','Übersicht Kalender mähen:')
            elif alm_mode == 'manual' and self.get_childitem('active_mode.uzsu.schaltuhr.active')== False:
                self.set_childitem('alm_mode.str','')
            elif alm_mode == 'manual' and self.get_childitem('active_mode.uzsu.schaltuhr.active')== True:
                self.set_childitem('alm_mode.str','Übersicht mähen nach UZSU:')
            else:
                self.set_childitem('alm_mode.str','unbekannt')
            self.logger.debug("alm_mode " + str(alm_mode))

            bareToolnumber = device_data_response['bareToolnumber']
            # Detect Modell
            myModells = {
                            "3600HA2300":"1000,1",
                            "3600HA2301":"1200,1",
                            "3600HA2302":"1100,1",
                            "3600HA2303":"13C,1",
                            "3600HA2304":"10C,1",
                            "3600HB0100":"350,2",
                            "3600HB0101":"400,2"
                        }
            try:
                myModell = myModells[bareToolnumber].split(',')[0]
                myModellType = int(myModells[bareToolnumber].split(',')[1])
            except:
                myModell = "unknown Modell ("+bareToolnumber+")"
                myModellType = 0
            self.set_childitem('visu.model', 'Indego '+myModell)
            self.set_childitem('visu.model_type', myModellType)
            
            self.set_childitem('bareToolnumber',bareToolnumber)
            self.logger.debug("bareToolnumber " + str(bareToolnumber))

            if 'alm_firmware_version' in device_data_response:
                alm_firmware_version = device_data_response['alm_firmware_version']
                if alm_firmware_version != self.get_sh().indego.alm_firmware_version():
                    self.set_childitem('alm_firmware_version.before',self.get_sh().indego.alm_firmware_version())
                    self.set_childitem('alm_firmware_version.changed', self.shtime.now() )
                    self.logger.info("indego updated firmware from {1} to {2}".format(self.get_sh().indego.alm_firmware_version(), str(alm_firmware_version)))

                    self.set_childitem('alm_firmware_version',alm_firmware_version)
                self.logger.debug("alm_firmware_version : {}".format(str(alm_firmware_version)))
    
    
    def check_state_triggers(self, myStatecode):
        myStatecode = str('%0.5d' %int(myStatecode))
        counter = 1
        while counter <=4:
            myItemName="trigger.state_trigger_" + str(counter) + ".state"
            myTrigger = self.get_childitem(myItemName).split("-")[0]
            if myStatecode == myTrigger:
                myTriggerItem="trigger.state_trigger_"+ str(counter)
                self.set_childitem(myTriggerItem, True)
            counter += 1


    def check_alarm_triggers(self, myAlarm):
            counter = 1
            while counter <=4:
                myItemName="trigger.alarm_trigger_" + str(counter) + ".alarm"
                myAlarmTrigger = self.get_childitem(myItemName)
                if myAlarmTrigger.lower() !='' and myAlarmTrigger.lower() in myAlarm.lower() :
                    myTriggerItem="trigger.alarm_trigger_"+ str(counter)
                    self.set_childitem(myTriggerItem, True)
                counter += 1        
    
    def state(self):
        if (self.get_childitem("wartung.wintermodus") == True or self.logged_in == False):
            return

        if (self.position_detection):
            self.position_count += 1
        state_response = self._get_url(self.indego_url + 'alms/' + self.alm_sn + '/state', self.context_id)
        states = state_response
        if state_response != False:
            self.set_childitem('online', True)
            self.logger.debug("indego state received :{}".format(str(state_response)))


            if 'error' in states:
                error_code = states['error']
                self.set_childitem('stateError',error_code)
                self.logger.error("error_code : {]".format(str(error_code)))
            else:
                error_code = 0
                self.set_childitem('stateError',error_code)
            state_code = states['state']
            try:
                if not str(state_code) in str(self.states) and len(self.states) > 0:
                    # got new unknown State-Code
                    self.states[state_code]=[str(state_code)+" unknown","unknown"]
                    # Store to Item 
                    newStruct = ""
                    for entry in self.states:
                        newStruct += '"'+str(entry)+'":'+ str(self.states[entry])
                    self.set_childitem('states_str', str("{"+newStruct)+"}")
                        
            except err as Exception:
                self.logger.warning("Error while adding new State-Code : {}".format(err))
                pass
            self.set_childitem('stateCode',state_code)
            myLastStateCode = self.get_childitem('webif.laststateCode')
            
            # Loggin the states in Timeline for the Web-Interface
            if state_code != myLastStateCode:
                self.set_childitem('webif.laststateCode', state_code)
                # Add to self rotating Array
                myLog = self.get_childitem('webif.state_protocoll')
                try:
                    if len (myLog) >= 500:
                        myLog = myLog[1:500]
                except:
                    pass
                now = self.shtime.now()
                myLog.append(str(now)[0:19]+'  State : '+str(state_code) + ' State-Message : ' + self.states[state_code][0])
                self.set_childitem('webif.state_protocoll', myLog)
                self.check_state_triggers(state_code)
                
            self.logger.debug("state code :".format(str(state_code)))
            if self.states[state_code][1] == 'dock':
                self.logger.debug('indego docked')
                self.alert_reset = True
                self.set_childitem('docked', True)
                self.set_childitem('moving', False)
                self.set_childitem('pause', False)
                self.set_childitem('help', False)
            if self.states[state_code][1] == 'moving':
                self.logger.debug('indego moving')
                self.alert_reset = True
                self.set_childitem('mowedDate', self.shtime.now())
                self.set_childitem('docked', False)
                self.set_childitem('moving', True)
                self.set_childitem('pause', False)
                self.set_childitem('help', False)
            if self.states[state_code][1] == 'pause':
                self.logger.debug('indego pause')
                self.alert_reset = True
                self.set_childitem('docked', False)
                self.set_childitem('moving', False)
                self.set_childitem('pause', True)
                self.set_childitem('help', False)
            if self.states[state_code][1] == 'hilfe':
                self.logger.debug('indego hilfe')
                self.set_childitem('docked', False)
                self.set_childitem('moving', False)
                self.set_childitem('pause', False)
                self.set_childitem('help', True)
                if self.alert_reset == True:
                    self.logger.debug("Alert aufgefrufen, self_alert_reset = True")
                    self.alert()
                else:
                    self.logger.debug("Alert nicht aufgefrufen, self_alert_reset = False")

            state_str = self.states[state_code][0]
            self.set_childitem('state_str', state_str )
            self.logger.debug("state str : {}".format(state_str))

            mowed = states['mowed']
            self.set_childitem('mowedPercent', mowed)
            self.logger.debug("mowed " + str(mowed))
            
            myLast_percent_mowed = self.get_childitem('visu.mow_track.last_percent_mowed')
            if (mowed == 0.0 and myLast_percent_mowed > 0.0):
                # New mow-Cycle startet
                self.set_childitem("visu.mow_track", [])
                #################################
            if state_code == 518 or state_code == 513 or state_code ==515 or state_code == 514 :    # 518 = mähe / 513 = schneide Rand / 515 = lade Karte / 514 = mähen, bestimme Ort
                # First run of position detection
                if not self.position_detection:
                    # Now set Position-Detection ON
                    myResult = self._post_url(self.indego_url + 'alms/' + self.alm_sn + '/requestPosition?count=100&interval=7', self.context_id, None, 10)
                    if myResult != True:
                        pass
                    # Now set scheduler for state to 8 Sec.
                    self.get_sh().scheduler.change('plugins.indego.state', cycle={8:None}) # Zum Testen von 6 auf 10 Sekunden geändert
                    self.position_detection = True
                    self.position_count = 0
                # Following runs of position detection
                if  (self.position_detection and self.position_count >= 90):
                    self.position_count = 0
                    myResult = self._post_url(self.indego_url + 'alms/' + self.alm_sn + '/requestPosition?count=100&interval=7', self.context_id, None, 10)
                    if myResult != True:
                        pass

                #################################
            self.set_childitem('visu.mow_track.last_percent_mowed', mowed)

            mowmode = states['mowmode']
            self.set_childitem('mowmode',mowmode)
            self.logger.debug("mowmode  :".format(str(mowmode)))

            total_operate = states['runtime']['total']['operate']
            self.set_childitem('runtimeTotalOperationMins',total_operate)
            self.logger.debug("total_operate : {}".format(str(total_operate)))
            total_operate = self._daystring(total_operate, 'min')
            self.set_childitem('runtimeTotalOperationMins.dhm',total_operate)

            total_charge = states['runtime']['total']['charge']
            self.set_childitem('runtimeTotalChargeMins',total_charge)
            self.logger.debug("total_charge " + str(total_charge))
            total_charge = self._daystring(total_charge, 'min')
            self.set_childitem('runtimeTotalChargeMins.dhm',total_charge)

            session_operate = states['runtime']['session']['operate']
            self.set_childitem('runtimeSessionOperationMins',session_operate)
            self.logger.debug("session_operate : {}".format(str(session_operate)))

            session_charge = states['runtime']['session']['charge']
            self.set_childitem('runtimeSessionChargeMins',session_charge)
            self.logger.debug("session_charge " + str(session_charge))

            if 'xPos' in states:
                xPos = states['xPos']
                self.set_childitem('xPos',xPos)
                self.logger.debug("xPos :{}".format(str(xPos)))

                yPos = states['yPos']
                self.set_childitem('yPos',yPos)
                self.logger.debug("yPos : {}".format(str(yPos)))

                svg_xPos = states['svg_xPos']
                self.set_childitem('svg_xPos',svg_xPos)
                self.logger.debug("svg_xPos :{}".format(str(svg_xPos)))

                svg_yPos = states['svg_yPos']
                self.set_childitem('svg_yPos',svg_yPos)
                self.logger.debug("svg_yPos :{}".format(str(svg_yPos)))
                
                # SVG-Position
                mySvgPos = self.get_childitem("visu.mow_track")
                newPos = str(svg_xPos)+","+str(svg_yPos)
                self.set_childitem('visu.svg_pos', 'svg_pos|'+newPos)
                if (len(mySvgPos) == 0):
                    mySvgPos.append(newPos)
                    self.set_childitem("visu.mow_track", mySvgPos)
                else:
                    if (newPos != mySvgPos[len(mySvgPos)-1]):
                        mySvgPos.append(newPos)
                        self.set_childitem("visu.mow_track", mySvgPos)

            map_update = states['map_update_available']
            self.logger.debug("map_update " + str(map_update))
            self.set_childitem('mapUpdateAvailable',map_update)

            if map_update:
                self.load_map()
                        
            # Postion-Detection during mowing
            self._check_state_4_protocoll()

    def load_map(self):
        self.logger.debug('lade neue Karte')
        garden = self._get_url(self.indego_url + 'alms/' + self.alm_sn + '/map?cached=0&showMower=1', self.context_id, 120)
        if garden == False:
            self.logger.warning('Map returned false')
        else:
            with open(self.img_pfad, 'wb') as outfile:
                outfile.write(garden)
            self.logger.debug('You have a new MAP')
            self.set_childitem('mapSvgCacheDate',self.shtime.now())
            self.set_childitem('webif.garden_map', garden.decode("utf-8"))
            
    def parse_map(self):
        myMap = self.get_childitem('webif.garden_map')
        myCustomDrawing = self.get_childitem('visu.add_svg_images')
        mowerColour = self.get_childitem('visu.mower_colour')
        mowerColour = mowerColour.split(':')[1]

        mowerColour = mowerColour.replace('"','')
        soupMap = BeautifulSoup(myMap, 'html.parser')
        mapArray = soupMap.prettify().split('\n')
        # Get the Mower-Position and extract it
        i= 0
        for line in mapArray:
            if '<circle' in line:
                mowerPos = line + '</circle>'
                myMowerPos = i
            if '<svg' in line:
                line = line.replace('<svg', '<svg id="svg_garden_map"')
                mapArray[i]=line
            i += 1
        # Delete the Mower-Position from the SVG
        del mapArray[myMowerPos+1]
        del mapArray[myMowerPos]
        # Change the Colour of the Mower and give an ID
        colorPos_one = mowerPos.find('fill="#')+7
        colorPos_two = mowerPos.find('"',colorPos_one)
        mowerPos = mowerPos.replace(mowerPos[colorPos_one:colorPos_two], mowerColour)
        mowerPos = mowerPos.replace('<circle', '<circle id="mower_pos"')

        # delete last Line ( closing the svg-vectors)
        mapLength = len(mapArray)-1
        del mapArray[mapLength]

        # Now add the custom paintings to the map

        if myCustomDrawing != None and myCustomDrawing != "":
            myCustomSoup = BeautifulSoup(myCustomDrawing, 'html.parser')
            customArray = myCustomSoup.prettify().split('\n')
            for line in customArray:
                mapArray.append(line)

        # finally add the Mower-Position and close again the svg-vectors
        mapArray.append('<g id="mower_track_id"></g>')
        mapArray.append(mowerPos)
        mapArray.append('</svg>')
        value =''
        for line in mapArray:
            value += line
        value = value.replace('\n','')
        value = value.replace('\r','')
        
        self.set_childitem('visu.map_2_display', value)
            
    def init_webinterface(self):
        """"
        Initialize the web interface for this plugin

        This method is only needed if the plugin is implementing a web interface
        """
        try:
            self.mod_http = Modules.get_instance().get_module(
                'http')  # try/except to handle running in a core version that does not support modules
        except:
            self.mod_http = None
        if self.mod_http == None:
            self.logger.error("Not initializing the web interface")
            return False

        import sys
        if not "SmartPluginWebIf" in list(sys.modules['lib.model.smartplugin'].__dict__):
            self.logger.warning("Web interface needs SmartHomeNG v1.5 and up. Not initializing the web interface")
            return False

        # set application configuration for cherrypy
        webif_dir = self.path_join(self.get_plugin_dir(), 'webif')
        config = {
            '/': {
                'tools.staticdir.root': webif_dir,
            },
            '/static': {
                'tools.staticdir.on': True,
                'tools.staticdir.dir': 'static'
            }
        }

        # Register the web interface as a cherrypy app
        self.mod_http.register_webif(WebInterface(webif_dir, self),
                                     self.get_shortname(),
                                     config,
                                     self.get_classname(), self.get_instance_name(),
                                     description='')

        return True



# ------------------------------------------
#    Webinterface of the plugin
# ------------------------------------------

import cherrypy
from jinja2 import Environment, FileSystemLoader


class WebInterface(SmartPluginWebIf):

    def __init__(self, webif_dir, plugin):
        """
        Initialization of instance of class WebInterface

        :param webif_dir: directory where the webinterface of the plugin resides
        :param plugin: instance of the plugin
        :type webif_dir: str
        :type plugin: object
        """
        self.logger = logging.getLogger(__name__)
        self.webif_dir = webif_dir
        self.plugin = plugin
        self.tplenv = self.init_template_environment()
        self.items = Items.get_instance()
        
        
    @cherrypy.expose
    def store_color_html(self, newColor = None):
        self.plugin.set_childitem('visu.mower_colour','mower_colour:"'+newColor[1:]+'"')
    
    
    @cherrypy.expose
    def store_state_trigger_html(self, Trigger_State_Item = None,newState=None):
        myItemSuffix=Trigger_State_Item
        myItem="trigger." + myItemSuffix + ".state"
        self.plugin.set_childitem(myItem,newState)    

    
    @cherrypy.expose
    def store_alarm_trigger_html(self, Trigger_Alarm_Item = None,newAlarm=None):
        myItemSuffix=Trigger_Alarm_Item
        myItem="trigger." + myItemSuffix + ".alarm"
        self.plugin.set_childitem(myItem,newAlarm)    


    @cherrypy.expose
    def store_credentials_html(self, encoded='', pwd = '', user= '', store_2_config=None):
        txt_Result = []
        result2send={}
        resultParams={}
        
        myCredentials = user+':'+pwd
        byte_credentials = base64.b64encode(myCredentials.encode('utf-8'))
        encoded = byte_credentials.decode("utf-8")
        txt_Result.append("encoded:"+encoded) 
        txt_Result.append("Encoding done")
        conf_file=self.plugin.sh.get_basedir()+'/etc/plugin.yaml'
        
        if (store_2_config == 'true'):
            new_conf = ""
            with open (conf_file, 'r') as myFile:
                for line in myFile:
                    if line.find('indego_credentials') > 0:
                        line = '    indego_credentials: '+encoded+ "\r\n"
                    new_conf += line 
            myFile.close()         
            txt_Result.append("replaced credentials in temporary file")
            with open (conf_file, 'w') as myFile:
                for line in new_conf.splitlines():
                    myFile.write(line+'\r\n')
            myFile.close()
            txt_Result.append("stored new config to filesystem")
            self.plugin.user = user
            self.plugin.password = pwd
            if self.plugin.logged_in:
                self.plugin._delete_auth()
            self.plugin._auth()
            self.plugin.logged_in = self.plugin._check_auth()
            if self.plugin.logged_in:
                txt_Result.append("logged in succesfully")
            else:
                txt_Result.append("login failed")
            myExperitation_Time = datetime.fromtimestamp(self.plugin.expiration_timestamp).strftime('%Y-%m-%d %H:%M:%S')
            myLastLogin = datetime.fromtimestamp(float(self.plugin.last_login_timestamp)).strftime('%Y-%m-%d %H:%M:%S')
            resultParams['logged_in']= self.plugin.logged_in
            resultParams['timeStamp']= myLastLogin + " / " + myExperitation_Time
            resultParams['SessionID']= self.plugin.context_id 
            resultParams['encoded']= encoded
            self.plugin.set_childitem('visu.refresh',True)
            txt_Result.append("refresh of Items initiated")
                
        result2send['Proto']=txt_Result
        result2send['Params']=resultParams
        return json.dumps(result2send)
    
    @cherrypy.expose
    def index(self, reload=None):
        """
        Build index.html for cherrypy

        Render the template and return the html file to be delivered to the browser

        :return: contents of the template after beeing rendered 
        """
        tmpl = self.tplenv.get_template('index.html')
        
        item_count = 0
        plgitems = []
        for item in self.items.return_items():
            if ('indego' in item.property.name):
                plgitems.append(item)
                item_count += 1
                
        try:
            my_state_loglines = self.plugin.get_childitem('webif.state_protocoll')
            state_log_file = ''
            for line in my_state_loglines:
                state_log_file += str(line)+'\n'
        except:
            state_log_file = 'No Data available right now\n'
        
        try:
            my_com_loglines = self.plugin.get_childitem('webif.communication_protocoll')
            com_log_file = ''
            for line in my_com_loglines:
                com_log_file += str(line)+'\n'
        except:
            state_log_file = 'No Data available right now\n'
            
        # get the login-times
        myExperitation_Time = datetime.fromtimestamp(self.plugin.expiration_timestamp).strftime('%Y-%m-%d %H:%M:%S')
        myLastLogin = datetime.fromtimestamp(float(self.plugin.last_login_timestamp)).strftime('%Y-%m-%d %H:%M:%S')
        # get the mower-colour
        myColour = '#'+self.plugin.get_childitem('visu.mower_colour')[14:-1]
        # get all the available states
        selectStates = []
        try:
            myStates = self.plugin.states
            for state in myStates:
                newEntry={}
                newEntry['ID']=str('%0.5d' %int(state))
                newEntry['Caption']=myStates[state][0]
                selectStates.append(newEntry)
            # add empty Entry
            newEntry={}
            newEntry['ID']='99999'
            newEntry['Caption']="kein State-Trigger"
            selectStates.append(newEntry)
        except:
            pass
        
        try:
            # get the actual triggers
            Trigger_1_state=self.plugin.get_childitem('trigger.state_trigger_1.state')
            Trigger_2_state=self.plugin.get_childitem('trigger.state_trigger_2.state')
            Trigger_3_state=self.plugin.get_childitem('trigger.state_trigger_3.state')
            Trigger_4_state=self.plugin.get_childitem('trigger.state_trigger_4.state')
            
            Alarm_Trigger_1=self.plugin.get_childitem('trigger.alarm_trigger_1.alarm')
            Alarm_Trigger_2=self.plugin.get_childitem('trigger.alarm_trigger_2.alarm')
            Alarm_Trigger_3=self.plugin.get_childitem('trigger.alarm_trigger_3.alarm')
            Alarm_Trigger_4=self.plugin.get_childitem('trigger.alarm_trigger_4.alarm')
        except:
            pass
         
        # add values to be passed to the Jinja2 template eg: tmpl.render(p=self.plugin, interface=interface, ...)
        return tmpl.render(p=self.plugin,
                           items=sorted(plgitems, key=lambda k: str.lower(k['_path'])),
                           item_count=item_count,
                           state_log_lines=state_log_file,
                           com_log_lines=com_log_file,
                           myExperitation_Time=myExperitation_Time,
                           myLastLogin=myLastLogin,
                           myColour=myColour,
                           myMap=self.plugin.get_childitem('webif.garden_map'),
                           selectStates=sorted(selectStates, key=lambda k: str.lower(k['ID'])),
                           Trigger_1_state=Trigger_1_state,
                           Trigger_2_state=Trigger_2_state,
                           Trigger_3_state=Trigger_3_state,
                           Trigger_4_state=Trigger_4_state,
                           Alarm_Trigger_1=Alarm_Trigger_1,
                           Alarm_Trigger_2=Alarm_Trigger_2,
                           Alarm_Trigger_3=Alarm_Trigger_3,
                           Alarm_Trigger_4=Alarm_Trigger_4 )



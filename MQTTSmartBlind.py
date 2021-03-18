# python3.6

####################################################################################
#
#                             `_`     `_,_`  _'                                  `,`  
#                            -#@@- >O#@@@@u B@@>                                 8@E  
#    :)ilc}` `=|}uccccVu}r"   VQz `@@#Mhzk= |8M   `=v}ucccccuY),    `~v}uVVcccccV#@$  
#  ^Q@#EMqK.I#@QRdMqqMdRQ@@Q, Q@B `@@BqqqW^ W@@` e@@QRdMMMMbEQ@@8: i#@BOMqqqqqqqM#@$  
#  D@@`    )@@x          <@@T Q@B `@@q      W@@`>@@l          :@@z`#@d           Q@$  
#  D@#     ?@@@##########@@@} Q@B `@@q      W@@`^@@@##########@@@y`#@W           Q@$  
#  0@#     )@@d!::::::::::::` Q@B `@@M      W@@`<@@E!::::::::::::``#@b          `B@$  
#  D@#     `m@@#bGPP}         Q@B `@@q      W@@` 3@@BbPPPV         y@@QZPPPPPGME#@8=  
#  *yx       .*icywwv         )yv  }y>      ~yT   .^icywyL          .*]uywwwwycL^-   
#                                                                                    
#      (c) 2021 Reified Ltd.     W: www.reified.co.uk     E: info@reified.co.uk
#
####################################################################################
#
# Present a stepper motor, driven by the Adafruit Stepper Motor Bonnet on a
# Raspberry Pi, as an IoT device over MQTT, controllable and monitorable via MQTT
# messages when connected to a MQTT broker.
#
####################################################################################
 
import random
import time
import json
import queue
import logging
import sys
import chronos

from datetime import datetime

from paho.mqtt import client as mqtt_client

import SmartBlindController

from adafruit_motor import stepper

########################################################################################
#
# class MQTTSmartBlind
#
########################################################################################

class MQTTSmartBlind:

	####################################################################################
	#
	# Initialisation
	#
	####################################################################################

	def __init__(self, 
	    host = '127.0.0.1', port = 1883, 
		blindNo = 1, blindID = '',
		steppingStyle = SmartBlindController.BlindSteppingStyle.DOUBLE,
		topicBase ='',
		loggingLevel = logging.NOTSET
		):
	
		self._debugLevel = loggingLevel
		
		self._logger = logging.getLogger('mqtt-smart-blind')
		self._logger.setLevel(self._debugLevel)
		
		self._dateFormat = '%Y-%d-%m %H.%M:%S.%f'		
		
		self._broker = host
		self._port = port

		self._isConnected = False
		self._client = None
		
		self._blindNo = blindNo
		self._blindControllerID = str(blindNo) if not blindID else blindID
		
		self._clientID = f'smartblind-session-{random.randint(0, 1000)}'  # Generate a default.

		self._topicBase = 'home/' if not topicBase else (
		    topicBase if (topicBase[-1]=='/') else f'{topicBase}/'
		)
		
		self._blindBase = f"{self._topicBase}blind/{self._blindControllerID}/"
		self._blindBaseLen = len(self._blindBase) # cache for speed.
		
		# Our subscribed topics.

		self._blindCalibrateTopic = self._blindBase + "calibrate/#"
		self._blindCommandTopic = self._blindBase + "control/#"
		self._blindSetStateTopic = self._blindBase + "position/set"
		
		# Our published topics.
		
		self._blindPubStartMotionTopic = self._blindBase + "position/start"
		self._blindPubInMotionTopic = self._blindBase + "position"
		self._blindPubEndMotionTopic = self._blindBase + "position/end"

		# Map of incoming-command representations to handlers for each.

		self._routingTable = {}

		# Initialisatiohow MQTT topics are mapped to blind control commands.
		
		self.__initialiseRouting() # Specifies which topic paths route to which callback.
				
		# Create a connection to the stepper motor and register to observe
		# any motion of the motor as it occurs.

		self._blindController = SmartBlindController.SmartBlindController(
			blindNo = self._blindNo,
			steppingStyle = steppingStyle,
			loggingLevel = logging.NOTSET
		)
		
		self._blindController.observe(self.__onMotionUpdate) # We want to observe the motion.

		# Connect to the MQTT broker and initiate the event loop for 
		# talking to it.

		self._client = self.__connectToBroker()
		self._client.loop_start()

		self.__awaitConnection()     # Wait for the MQTT broker.

		self.__publishStartMotionPosition(self._client, 0, 0) # Initial publish.
		self.__publishInMotionPosition(self._client, 0, 0) # Initial publish.
		self.__publishEndMotionPosition(self._client, 0, 0) # Initial publish.
			
		# username = 'emqx'
		# password = 'public'
			
		## Old signature for MQTT v3.1.1 and v3.1 is:
		## on_ subscribe(client, userdata, mid, granted_qos)
		## and for the MQTT v5.0 client:
		## on_subscribe(client, userdata, mid, granted_qos, properties=None)

		## Old signature for MQTT v3.1.1 and v3.1 is:
		## unsubscribe_callback(client, userdata, mid)
		## and for the MQTT v5.0 client:
		## unsubscribe_callback(client, userdata, mid)
	
	####################################################################################
	#
	# start(self)
	#
	####################################################################################

	def start(self):
	    
		self._blindController.start()
		
	####################################################################################
	#
	# stop()
	#
	####################################################################################

	def stop(self):
	    
		self._blindController.stop()
		
	####################################################################################
	#
	# tryStart(self) => bool
	#
	####################################################################################

	def tryStart(self) -> bool:
	    
		return self._blindController.tryStart()
		
	####################################################################################
	#
	# tryStop()
	#
	####################################################################################

	def tryStop(self):
	    
		return self._blindController.tryStop()
		
	####################################################################################
	#
	# run(self)
	#
	####################################################################################

	def run(self):

		try:
			# Resting position publiscations are a sub-set of position publications.
			# Clients could subscribe to either one, or both.
			# The geneal position publications show progress as the blind moves, whereas
			# the resting position publication reports only a new resting place upon
			# arrival at that position.
			
			self._blindController.run()  # Begin the stepper motor controller (blocking).
		
		except KeyboardInterrupt:
			self._logger.info("*** Interrupted.")

	####################################################################################
	#
	# __initialiseRouting(self)
	#
	####################################################################################

	def __initialiseRouting(self):

		self.__registerCommand("calibrate/set-step-size", self.__executeSetStepSize)
		self.__registerCommand("calibrate/wind", self.__executeWind)
		self.__registerCommand("calibrate/counter-wind", self.__executeCounterWind)
		self.__registerCommand("calibrate/set-opened", self.__executeSetOpened)
		self.__registerCommand("calibrate/set-closed", self.__executeSetClosed)
		self.__registerCommand("calibrate/set-speed", self.__executeSetSpeed)
		self.__registerCommand("calibrate/set-polarity", self.__executeSetPolarity)
		
		self.__registerCommand("control/open", self.__executeOpen)
		self.__registerCommand("control/close", self.__executeClose)
		self.__registerCommand("control/go-to", self.__executeGoTo)
		self.__registerCommand("control/stop", self.__executeStop)
		
		self.__registerCommand("position/set", self.__executeGoTo) # Synonym for control/go-to.

	####################################################################################
	#
	# __registerCommand(self, command, params, method)
	#
	####################################################################################

	def __registerCommand(self, command, method):

		if (command in self._routingTable):
			raise Exception(f"Command {command} is already registered.")
			
		self._routingTable[command] = method
		
	####################################################################################
	#
	# __connectToBroker(self)
	#
	####################################################################################

	def __connectToBroker(self):

		# client = mqtt_client.Client(client_id,transport=’websockets’)
		# client = mqtt_client.Client(client_id=””, clean_session=True, userdata=None, protocol = MQTTv311, transport=”tcp”)
	
		client = mqtt_client.Client(self._clientID)
	
		# client.username_pw_set(username, password)    # TODO
	
		client.on_connect = self.__onConnect
		client.on_disconnect = self.__onDisconnect
		
		client.connect(self._broker, self._port)
		
		return client

	####################################################################################
	#
	# __awaitConnection(self)
	#
	####################################################################################

	def __awaitConnection(self):

		while not self._isConnected:
			self._logger.debug("Awaiting connection...")
			time.sleep(1)
			
	####################################################################################
	#
	# __onConnect(client, userdata, flags, rc)
	#
	####################################################################################

	def __onConnect(self, client, userdata, flags, rc):

		if rc == 0:
			self._logger.info("Connected to MQTT Broker!")
			self._isConnected = True
			
			# (Re)subscribe whenever a connection is established.
			self.__subscribeToTopics(client)

		else:
			self._logger.error("Failed to connect, return code %d\n", rc)

	####################################################################################
	#
	# __onDisconnect(self, client, userdata, rc)
	#
	####################################################################################

	def __onDisconnect(self, client, userdata, rc):

		self._isConnected = false
		self._logger.warning("disconnecting: reason is " +str(rc))

	####################################################################################
	#
	# __onPublish(self, obj, mid)
	#
	####################################################################################

	def __onPublish(self, obj, topic):
	
		self._logger.debug("Published to {topic}.")

	####################################################################################
	#
	# __onSubscribe(self, obj, mid, granted_qos)
	#
	####################################################################################

	def __onSubscribe(self, obj, topic, grantedQoS):
	
		# Don't call this. Documentation says 4 args, but 5 seem expected.
		# Also, no idea what each argument represents. Empirical tinkering
		# has not be useful for enlightenment either.
		
		self._logger.info(f"Subscribed to {topic}: granted QoS of {grantedQoS}")

	####################################################################################
	#
	# __onLog(self, obj, level, string)
	#
	####################################################################################

	def __onLog(self, obj, level, string):
	
		# No idea what this callback represents. Avoid using (for now at least).
		pass
		
	####################################################################################
	#
	# __onMessage(self, client, userdata, message)
	#
	####################################################################################

	def __onMessage(self, client, userdata, message):

		# This is a callback invoked from the MQTT client upon a message arrival.
		# As its not our own thread, don't let any exceptions propagate (as we can't be
		# sure how the MQTT client code will manage it, if at all and how/if we manage
		# a context-specific message is not of its concern).
		
		try:
			self.__processMessage(message);	

		except Exception as ex: # Catch all errors as its not our thread!
			self._logger.error(f"Error processing message {message}: {ex}.")

		except: # Catch all errors as this is not our thread!
			self._logger.error("Error processing message {message}.")
			
	####################################################################################
	#
	# __subscribeToTopics(self, client)
	#
	####################################################################################

	def __subscribeToTopics(self, client):

		self._logger.debug(f"Subscribing to topics based at {self._blindBase}")
	
		client.subscribe(self._blindCalibrateTopic) # Incoming calibration commands.
		client.subscribe(self._blindCommandTopic)   # Incoming normal-use motion commands.
		client.subscribe(self._blindSetStateTopic)  # Incoming property/attribute oriented motion 
		
		client.on_message = self.__onMessage
	
		# Options? QoS?
	
	####################################################################################
	#
	# __publish(self, client, topic, payload)
	#
	####################################################################################

	def __publish(self, client, topic, payload, QoS, retain):
		
		result = client.publish(topic, payload, QoS, retain)
		status = result[0] # result: [0, 1]
		
		if status == 0:
			self._logger.debug(f"Published {topic} message {payload}.")
		else:
			self._logger.warning(f"Failed to send to topic {topic} message {payload}.")

	####################################################################################
	#
	# __onMotionUpdate(self, targetPosition, actualPosition, motionEvent)
	#
	####################################################################################

	def __onMotionUpdate(self, targetPercentage, actualPercentage, motionEvent):
		
		# This is a callback invoked from the motor client upon a motion update.
		# As its not our own thread, don't let any exceptions propagate (as we can't be
		# sure how the motor client code will manage it, if at all and how/if we manage
		# a context-specific message is not of its concern).
		
		try:
			self.__processMotionUpdate(targetPercentage, actualPercentage, motionEvent);	

		except Exception as ex: # Catch all errors as its not our thread!
			self._logger.error(f"Error processing blind motion update: {ex}.")

		except: # Catch all errors as this is not our thread!
			self._logger.error("Error processing motion update (target {targetPercentage}, actual {actualPercentage}).")
			
	####################################################################################
	#
	# __processMotionUpdate(self, targetPercentage, actualPercentage, motionEvent)
	#
	####################################################################################

	def __processMotionUpdate(self, targetPercentage, actualPercentage, motionEvent):
		
		# This is a callback invoked from the async blind controller when motion occurs.
		
		# We treat the start/end motion points as seperate events, in that when they
		# occur we public their occurance  as *well* as in-motion events because 
		# any client might have separate topics for start/end/in-motion events and
		# yet subscribing to in-motion (only) should still provide notification of the 
		# full extent of motion. This may be useful, depending upon how the MQTT topics
		# for each are defined.
		
		if (motionEvent == SmartBlindController.MotionEvent.STARTING):
			self.__publishStartMotionPosition(self._client, targetPercentage, actualPercentage)
			self.__publishInMotionPosition(self._client, targetPercentage, actualPercentage)
		
		elif (motionEvent == SmartBlindController.MotionEvent.MOVING):
			self.__publishInMotionPosition(self._client, targetPercentage, actualPercentage)

		elif (motionEvent == SmartBlindController.MotionEvent.STOPPED):
			self.__publishInMotionPosition(self._client, targetPercentage, actualPercentage)
			self.__publishEndMotionPosition(self._client, targetPercentage, actualPercentage)
		
		else:
			self._logger.debug(f"Processing motion update, unexpected motion event {motionEvent}.")
			
	####################################################################################
	#
	# __publishStartMotionPosition(self, client, targetPercentage, actualPercentage)
	#
	####################################################################################

	def __publishStartMotionPosition(self, client, targetPercentage, actualPercentage):
				
		self.__publish(
			client, 
			self._blindPubStartMotionTopic, 
			self.__makePositionPayload(targetPercentage, actualPercentage),
			QoS = 0,  # Its not important that every bit of motion gets through.
			retain = False
		)

	####################################################################################
	#
	# __publishInMotionPosition(self, client, targetPercentage, actualPercentage)
	#
	####################################################################################

	def __publishInMotionPosition(self, client, targetPercentage, actualPercentage):
				
		self.__publish(
			client, 
			self._blindPubInMotionTopic, 
			self.__makePositionPayload(targetPercentage, actualPercentage),
			QoS = 0,  # Its not important that every bit of motion gets through.
			retain = False
		)

	####################################################################################
	#
	# __publishEndMotionPosition(self, client, targetPercentage, actualPercentage)
	#
	####################################################################################

	def __publishEndMotionPosition(self, client, targetPercentage, actualPercentage):
				
		self.__publish(
			client, 
			self._blindPubEndMotionTopic, 
			self.__makePositionPayload(targetPercentage, actualPercentage),
			QoS = 1,  # We want the end point to get through. Dups are fine.
			retain = False
		)

	####################################################################################
	#
	# __makePositionPayload(self, targetPercentage, actualPercentage)
	#
	####################################################################################

	def __makePositionPayload(self, targetPercentage, actualPercentage):
	
		return json.dumps({ 
			"target" : round(targetPercentage), # Whole percentages only.
			"actual" : round(actualPercentage)
		})
	
	####################################################################################
	#
	# __processMessage(self, message)
	#
	####################################################################################

	def __processMessage(self, message):

		payload = message.payload.decode() # its an encoded string, so we need to decode it.
		self._logger.debug(f"Received topic {message.topic} with {payload}")

		command = self.__parseTopicForCommand(message.topic)		
		self._logger.debug(f"Parsed command '{command}'")
		
		self.__executeCommand(command, payload)

	####################################################################################
	#
	# __parseTopicForCommand(self, topic)
	#
	####################################################################################

	def __parseTopicForCommand(self, topic):
	
		index = self._blindBaseLen
		command = topic[index:]
		
		return command
	
	####################################################################################
	#
	# __executeCommand(self, command, payload)
	#
	####################################################################################

	def __executeCommand(self, command, payload):

		if (not (command in self._routingTable)):
			raise Exception(f"Unexpected command {command} (with {payload}).")

		handler = self._routingTable[command]
		handler(payload)

	####################################################################################
	#
	# __executeWind(self, payload)
	#
	####################################################################################

	def __executeWind(self, payload):	
			
		params = self.__parseJson(payload)
		steps = self.__getParam(params, 'steps')
		
		self._blindController.wind(steps)

	####################################################################################
	#
	# __executeCounterWind(self, payload)
	#
	####################################################################################

	def __executeCounterWind(self, payload):	
	
		params = json.loads(payload)
		steps = self.__getParam(params, 'steps')
		
		self._blindController.counterWind(steps)

	####################################################################################
	#
	# __executeSetOpened(self, payload)
	#
	####################################################################################

	def __executeSetOpened(self, payload):

		self._blindController.setOpenedPoint()
		
	####################################################################################
	#
	# __executeSetClosed(self, payload)
	#
	####################################################################################

	def __executeSetClosed(self, payload):

		self._blindController.setClosedPoint()

	####################################################################################
	#
	# __executeOpen(self, payload)
	#
	####################################################################################

	def __executeOpen(self, payload):

		self._blindController.open()

	####################################################################################
	#
	# __executeClose(self, payload)
	#
	####################################################################################

	def __executeClose(self, payload):

		self._blindController.open()

	####################################################################################
	#
	# __executePosition(self, payload)
	#
	####################################################################################

	def __executeGoTo(self, payload):

		params = json.loads(payload)
		percentage = self.__getParam(params, 'percentage')
		
		self._blindController.moveTo(percentage)

	####################################################################################
	#
	# __executeStop(self, payload)
	#
	####################################################################################

	def __executeStop(self, payload):

		self._blindController.halt()

	####################################################################################
	#
	# __executeSetStepSize(self, payload)
	#
	####################################################################################

	def __executeSetStepSize(self, payload):	
	
		params = self.__parseJson(payload)
		stepSize = self.__getParam(params, 'step-size')

		self._blindController.stepSize(stepSize)

	####################################################################################
	#
	# __executeSetSpeed(self, payload)
	#
	####################################################################################

	def __executeSetSpeed(self, payload):

		params = json.loads(payload)
		speed = self.__getParam(params, 'factor') # 0.1 - 1.0   (arbitrary units)
		
		speed = __forceInRange(speed, 0.1, 1.0)

		# TODO: Convert a single speed factor to an associated step delay.
		
		# self._blindController.motionStepDelay(self, delaySecs)
		raise NotImplementedError("MQTTSmartBlind.__executeSetSpeed not (yet) implemented.")

	####################################################################################
	#
	# __executeSetPolarity(self, payload)
	#
	####################################################################################

	def __executeSetPolarity(self, payload):

		params = json.loads(payload)
		self._openIs100 = self.__getParam(params, 'topIs100')
		
		self._blindController.setPolarity(self._openIs100)

	####################################################################################
	#
	# __parseJson(self, params)
	#
	####################################################################################

	def __parseJson(self, str):
	
		try:
			params = json.loads(str)
		
		except Exception as ex: # Add contextual (JSON specific) info so more comprehensible.
			raise Exception(f"Failed to parse JSON '{str}': {ex}") # More intelligible.
		
		return params
		
	####################################################################################
	#
	# __getParam(self, params)
	#
	####################################################################################

	def __getParam(self, params, name):
	
		if (not name in params):
			raise Exception(f"Missing parameter '{name}'")
			
		value = params[name]
		
		return value
		
	####################################################################################
	#
	# __addTimestamp(self, params)
	#
	####################################################################################

	def __addTimestamp(self, params):
	
		when = datetime.now().strftime(self._dateFormat)
		params['timestamp'] = when
	
	####################################################################################
	#
	# __del__(self)
	#
	####################################################################################

	def __del__(self):
	
		try:
			self._client.loop_stop()
			
		except:
			self._logger.error(f"MQTTSmartBlind dtor failed.")
			pass

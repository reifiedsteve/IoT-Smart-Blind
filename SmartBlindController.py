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

from enum import Enum

from datetime import datetime

from paho.mqtt import client as mqtt_client

import AsyncStepperMotor
from adafruit_motor import stepper

########################################################################################
#
# class MotionEvent
#
########################################################################################

class MotionEvent(Enum):
	STARTING = 1
	MOVING = 2
	STOPPED = 3
	
####################################################################################
#
# class BlindSteppingStyle
#
####################################################################################

class BlindSteppingStyle(Enum):
	SINGLE = stepper.SINGLE
	DOUBLE = stepper.DOUBLE
	INTERLEAVE = stepper.INTERLEAVE
	MICROSTEP = stepper.MICROSTEP		

########################################################################################
#
# class SmartBlindController
#
########################################################################################

class SmartBlindController:

	####################################################################################
	#
	# __init__(self, blindNo, steppingStyle, loggingLevel)
	#
	####################################################################################

	def __init__(self, 
		blindNo = 1,
		steppingStyle = AsyncStepperMotor.MotorSteppingStyle.DOUBLE,
		loggingLevel = logging.NOTSET
		):
		
		self._debugLevel = loggingLevel
		self._logger = logging.getLogger('SmartBlindController')
		self._logger.setLevel(self._debugLevel)
				
		self._blindNo = blindNo

		# Initialisation.
		# Note: the motor ID is set to he same as the blind ID.

		self._stepperNo = blindNo
		self._steppingStyle = steppingStyle		
		self._stepSize = 50   # Semi-arbitrary, but only used during calibration.
		
		# Anything called "position" refers to the raw motor position (effectively
		# in arbitary units). 
		
		self._openedPosition = None
		self._closedPosition = None
		
		self._motorCurrentPosition = 0
		
		self._targetPercentage = 0
		self._actualPercentage = 0
		
		self._openIs100 = True # Position 100% could be top or bottom (user preference).
		
		# Create a connection to the stepper motor and register to observe
		# any motion of the motor as it occurs.

		self._motorController = AsyncStepperMotor.AsyncStepperMotor(
			stepperNo = self._blindNo,
			loggingLevel = logging.NOTSET
		)
		
		self._motorController.observe(self._onMotionUpdate) # We want to observe the motion.

		self._observer = None
			
	####################################################################################
	#
	# observe(self, observer)
	#
	####################################################################################

	def observe(self, observer):
	
		self._observer = observer
		
	####################################################################################
	#
	# start(self)
	#
	####################################################################################

	def start(self):
	    
		self._motorController.start()
		
	####################################################################################
	#
	# stop()
	#
	####################################################################################

	def stop(self):
	    
		self._motorController.stop()
		
	####################################################################################
	#
	# tryStart(self)
	#
	####################################################################################

	def tryStart(self) -> bool:
	    
		return self._motorController.tryStart()
		
	####################################################################################
	#
	# tryStop()
	#
	####################################################################################

	def tryStop(self) -> bool:
	    
		return self._motorController.tryStop()
		
	####################################################################################
	#
	# run(self)
	#
	####################################################################################

	def run(self):

		try:
			self._motorController.run()  # Begin the stepper motor controller (blocking).
		
		except KeyboardInterrupt:
			self._logger.info("*** Interrupted.")

	####################################################################################
	#
	# wind(self, noOfSteps)
	#
	####################################################################################

	def wind(self, noOfSteps):	
			
		self._motorController.moveBy(noOfSteps * self._stepSize)
		self._logger.info(f"Wind by {noOfSteps} step{'s' if (noOfSteps > 1) else ''}.")

	####################################################################################
	#
	# counterWind(self, noOfSteps)
	#
	####################################################################################

	def counterWind(self, noOfSteps):	
	
		self._motorController.moveBy(noOfSteps * -self._stepSize)
		self._logger.info(f"Counter wind by {noOfSteps} step{'s' if (noOfSteps > 1) else ''}.")

	####################################################################################
	#
	# setOpenedPoint(self)
	#
	####################################################################################

	def setOpenedPoint(self):

		self._openedPosition = self._motorCurrentPosition
		self._logger.debug(f"Set opened position to {self._openedPosition}.")
		
	####################################################################################
	#
	# setClosedPoint(self)
	#
	####################################################################################

	def setClosedPoint(self):

		self._closedPosition = self._motorCurrentPosition
		self._logger.debug(f"Set closed position to {self._closedPosition}.")

	####################################################################################
	#
	# open(self)
	#
	####################################################################################

	def open(self):

		if (self._openedPosition == None):
			raise Exception("Opened point not yet calibrated.")
			
		self._motorController.moveTo(self._openedPosition)
		self._logger.debug(f"Opening blind (moving to position of {self._openedPosition}).")

	####################################################################################
	#
	# close(self)
	#
	####################################################################################

	def close(self):

		if (self._closedPosition == None):
			raise Exception("Closed point not yet calibrated.")

		self._motorController.moveTo(self._closedPosition)
		self._logger.debug(f"Closing blind (moving to position of {self._closedPosition}).")

	####################################################################################
	#
	# moveTo(self, percentage)
	#
	####################################################################################

	def moveTo(self, percentage):

		if (self._openedPosition == None):
			raise Exception("Opened point not yet calibrated.")

		if (self._closedPosition == None):
			raise Exception("Closed point not yet calibrated.")

		if (self._openedPosition == self._closedPosition): # Avoid div zero, etc.
			raise Exception("Opened and closed points are the same.")

		position = self._calculatePositionFromPercentage(
			percentage,
			self._openedPosition,
			self._closedPosition,
			self._openIs100
		)
		
		self._motorController.moveTo(position)
		
		self._logger.info(f"Moving to {percentage}%.")

	####################################################################################
	#
	# halt(self)
	#
	####################################################################################

	def halt(self):

		self._motorController.halt()		
		self._logger.info(f"Halt.")

	####################################################################################
	#
	# stepSize(self, stepSize)
	#
	####################################################################################

	def stepSize(self, stepSize):	
	
		self._stepSize = stepSize;	
		self._logger.info(f"Set step size to {stepSize}.")

	####################################################################################
	#
	# setPolarity(self, payload)
	#
	####################################################################################

	def setPolarity(self, openIs100):

		self._openIs100 = openIs100
		self._logger.info(f"Interpret 100% as fully " + ("open" if self._openIs100 else "closed") + ".")

	####################################################################################
	#
	# setSpeed(self, speed)
	#
	####################################################################################

	def setSpeed(self, speed): # 0.1 - 1.0   (arbitrary units)
		
		speed = _forceInRange(speed, 0.1, 1.0)

		# TODO: Convert a single speed factor to an associated step delay.		
		# self._motorController.motionStepDelay(self, delaySecs)
		
		raise NotImplementedError("Not (yet) implemented.")

	####################################################################################
	#
	# _onMotionUpdate(self, targetPosition, actualPosition)
	#
	####################################################################################

	def _onMotionUpdate(self, targetPosition, actualPosition):
		
		# This is a callback invoked from the motor client upon a motion update.
		# As its not our own thread, don't let any exceptions propagate (as we can't be
		# sure how the motor client code will manage it, if at all and how/if we manage
		# a context-specific message is not of its concern).
		
		try:
			self._processMotionUpdate(targetPosition, actualPosition);	

		except Exception as ex: # Catch all errors as its not our thread!
			self._logger.error(f"Error processing stepper motor motion update: {ex}.")

		except: # Catch all errors as this is not our thread!
			self._logger.error("Error processing message.")
			
	####################################################################################
	#
	# _processMotionUpdate(self, targetPosition, actualPosition)
	#
	####################################################################################

	def _processMotionUpdate(self, targetPosition, actualPosition):
		
		# This is a callback invoked from the async motor controller when motion occurs.
		
		self._motorCurrentPosition = actualPosition # Note how far the motor has travelled so far.

		calibrating = (self._openedPosition == None) or (self._closedPosition  == None)
		
		if (not calibrating):
			
			# We get informed (from the motor controller) of new positions, but
			# clients deal in percentage of distance bewtween fully-opened and
			# fully-closed, hence we need to transform positions originating
			# from the motor to a percentage.
						
			targetPercentage = self._calculatePercentageFromPosition(
				targetPosition,
				self._openedPosition,
				self._closedPosition,
				self._openIs100
			)
			
			actualPercentage = self._calculatePercentageFromPosition(
				actualPosition,
				self._openedPosition,
				self._closedPosition,
				self._openIs100
			)
			
			# We publish the target as well as the current position as this may be
			# useful to any clients. It also allows a client to determine when the 
			# target has been changed (e.g. by another client and what that new 
			# target is), which is particularly useful when the new target value is
			# otherwise not published nor knowable by subscribing to all positional
			# commands on the message-bus (e.g. because of a "stop motion" command).
			# Besides which, delivering the two pieces of information synchronously
			# may make for simpler client logic.

			# For clients that want to know *only* of resting positions (and not
			# motion progress) or wish to have motion completion reported separately,
			# we publish that information too here.
			
			prevTargetPercentage = self._targetPercentage
			prevActualPercentage = self._actualPercentage
			
			wasMoving = (prevTargetPercentage != prevActualPercentage)
			nowMoving = (targetPercentage != actualPercentage)
			
			if (not wasMoving and nowMoving):
				self._observer(targetPercentage, actualPercentage, MotionEvent.STARTING)
			
			if (wasMoving and not nowMoving):
				self._observer(targetPercentage, actualPercentage, MotionEvent.STOPPED)

			else: # mid-journey ongoing motion.
				self._observer(targetPercentage, actualPercentage, MotionEvent.MOVING)
			
			self._targetPercentage = targetPercentage
			self._actualPercentage = actualPercentage
			
		else:
			self._logger.debug(f"Calibration not yet complete: Opened is {self._openedPosition}. Closed is {self._closedPosition}.")
			
	####################################################################################
	#
	# _calculatePositionFromPercentage(self, percentage, openedPosition, closedPosition, topIs100)
	#
	####################################################################################

	def _calculatePositionFromPercentage(self, percentage, openedPosition, closedPosition, topIs100) -> int:
	
		max = openedPosition if topIs100 else closedPosition
		min = closedPosition if topIs100 else openedPosition
	
		position = min + ((max - min) / 100.0 * percentage)	
		
		## TODO; Ensure/force in range min..max

		return int(position) # Positions are integral.
		
	####################################################################################
	#
	# _calculatePercentageFromPosition(self, position, openedPosition, closedPosition, topIs100)
	#
	####################################################################################

	def _calculatePercentageFromPosition(self, position, openedPosition, closedPosition, topIs100) -> float:
	
		max = openedPosition if topIs100 else closedPosition
		min = closedPosition if topIs100 else openedPosition
		
		percentage = (position - min) / (max - min) * 100.0
		
		## TODO; Ensure/force in range 0..100
		
		return percentage

	####################################################################################
	#
	# _forceInRange(self, value, min, max)
	#
	####################################################################################

	def _forceInRange(value, min, max):
		result = min if value < min else value
		result = max if value > max else value
		return result
		

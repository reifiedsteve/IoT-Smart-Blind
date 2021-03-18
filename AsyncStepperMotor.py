# python3.6

####################################################################################
#
#                             `_`     `_,_`  _'                                  `,
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
# Provides an asynchronous means of driving a stepper motor connected to an Adafruit
# Stepper Motor Bonnet on a Raspberry Pi.
#
####################################################################################
#
# Usage example:
#
#     import AsyncStepperMotor
#     import time
#
#     def onMotion(targetPos, actualPos):
#         print(f"Moving: to {targetPos} from {actualPos}.")
#
#        ...
#
#     motor =  AsyncStepperMotor.AsyncStepperMotor(
#         stepperNo = 1,
#         steppingStyle = stepper.DOUBLE,
#         loggingLevel = logging.DEBUG
#     )
#
#     motor.observe(onMotion)
#
#     # Note: Commands issued are *not* sequentially executed to completion. 
#     # A newly issued command will override any motion that is currently in
#     # progress in order to give real-time control of the motor (as if 
#     # pushing physical control buttons).
#
#     motor.moveBy(50)     # returns immediately before completion.
#     time.sleep(5)
#
#     motor.moveTo(1000)   # returns immediately before completion.
#     time.sleep(1)        # probably not enough time to get to pos 1000
#     motor.stop()         # stops the motion, whereever the position.
#
#     motor.mark('opened') # returns immediately before completion.
#
#     motor.moveTo(-1000)  # returns immediately before completion.
#     time.sleep(10)       # give it time to get there before marking it.
#     motor.mark('closed') # returns immediately before completion.
#
#     time.sleep(60)
#
#     # Note: in the following two lines, it (almost certainly)
#     # neve reaches the 'open' position because as soon as the
#     # command is issued to go to 'open', we immediately change
#     # our  mind and instruct the motor to go to the 'closed'
#     # position.
#
#     motor.goto('opened')  # goes to the 'opened' position
#     motor.goto('closed')  # goes to the 'closed' position
#
#
#     # There are also options for setting various options on the
#     # stepper motor.
#
#     TODO !!!! (continue this example code)
#
####################################################################################

import time
import queue
import logging

import chronos

from datetime import datetime
from threading import Event

from enum import Enum

from concurrent.futures import ThreadPoolExecutor
from time import sleep

from adafruit_motorkit import MotorKit
from adafruit_motor import stepper

####################################################################################
#
# class _MotorCommand
#
####################################################################################

class _MotorCommand:

	def __init__(self, command, desc):
		self._command = command
		self._description = desc

	def execute(self):
		self._command()

	def _str_(self):
		return self._description

####################################################################################
#
# class MotorSteppingStyle
#
####################################################################################

class MotorSteppingStyle(Enum):
	SINGLE = stepper.SINGLE
	DOUBLE = stepper.DOUBLE
	INTERLEAVE = stepper.INTERLEAVE
	MICROSTEP = stepper.MICROSTEP

####################################################################################
#
# class AsyncStepperMotor
#
####################################################################################

class AsyncStepperMotor:

	################################################################################
	#
	# __init__(self, stepperNo , steppingStyle, loggingLevel)
	#
	################################################################################

	def __init__(self, stepperNo = 1, steppingStyle = stepper.DOUBLE, loggingLevel = logging.NOTSET):

		self._debugLevel = loggingLevel

		self._logger = logging.getLogger('AsyncStepperMotor')
		self._logger.setLevel(self._debugLevel)

		self._dateFormat = '%Y-%d-%m %H.%M:%S.%f'

		### 28BYJ48 Specific Info. We ignore it, but it's here anyway.
		### We rely upon contextual calibration to account for different motors.
		### motorStepsPerRev = 64     # 5.625 degs per stride
		### gearingRatio = 63.68395
		### stepsPerRev = motorStepsPerRev * gearingRatio

		self._commandQueue = queue.Queue()  # Ready-baked thread-safe queue.

		# Define our motion behaviour configuration.

		self._motorSteppingStyle = steppingStyle
		self._motorMotionReversed = False

		# Motion progress reporting intervals and the countdown timers
		# used to determine if those intervals have expired.

		self._idlingReportInterval = 5.0 # seconds
		self._idlingReportCountdownTimer = chronos.CountdownTimer(self._idlingReportInterval)

		self._motionReportInterval = 0.2 # seconds
		self._motionReportCountdownTimer = chronos.CountdownTimer(self._motionReportInterval)

		# The selected countdown time, depending upon whether the motor
		# is in motion or not.

		self._countdownTimer = self._idlingReportCountdownTimer

		# A map of named (labelled) positions against their notional
		# numeric position.

		self._markedPositions = {}

		# Motor position and request for change of motor position.
		# We look for the target differing from the current state
		# to trigger motion processing.

		self._motorPosition = 0
		self._targetMotorPosition = self._motorPosition

		self._prevMotorPosition = self._motorPosition
		self._prevTargetMotorPosition = self._targetMotorPosition

		# Client code may optionall observer progress of the motion
		# motor. 
		#
		# Request to change the state reporting interval.
		# We have two reporting intervals. One for when the motor
		# is stationary, and another for when it is moving.
		#
		# We report regularly even when stationary as it can
		# potentially offer client code simpler logic.
		#
		# We have a separate reporting interval for when the motor
		# is in motion as there is a likely need for more regular
		# updates then.
		#
		# In any case, both intervals are configurable by client code.

		self._targetIdlingReportInterval = self._idlingReportInterval
		self._targetMotionReportInterval = self._motionReportInterval

		# Initially, there is no observer of any motion.

		self._observer = None

		self._lastSteadyStatePosition = 0

		self._motionCompleteEvent = Event()
		self._motionCompleteEvent.set() # As not initially in motion.

		self._waitCompleteEvent = Event()
		self._waitCompleteEvent.set() # As not initially waiting.

		self._threadPool = ThreadPoolExecutor(1)
		self._future = None
		self._running = False
		self._looping = True

		# Initialisation of the underlying motor library. The Adafruit
		# stepper motor bonnet supports up to two stepper motors. An
		# instance of this class controls one or the other.

		self._kit = MotorKit()

		if (stepperNo < 1) or (stepperNo > 2):
		    raise Exception(f'Invalid stepper number {stepperNo}')

		self._stepperMotor = self._kit.stepper1 if stepperNo == 1 else self._kit.stepper1

	################################################################################
	#
	# moveBy(self, steps)
	#
	################################################################################

	def moveBy(self, steps):

		command = _MotorCommand(
			lambda : self._moveBy(steps),
			f"move by {steps}"
		)

		self._queueCommand(
			command
		)

	################################################################################
	#
	# moveTo(self, position)
	#
	################################################################################

	def moveTo(self, position):

		self._queueCommand(
			_MotorCommand(
				lambda : self._moveTo(position),
				f"move to {position}"
			)
		)

	################################################################################
	#
	# halt(self)
	#
	################################################################################

	def halt(self):

		self._queueCommand(
			_MotorCommand(
				lambda : self._halt(),
				"halt"
			)
		)

	################################################################################
	#
	# mark(self, label)
	#
	################################################################################

	def mark(self, label):

		self._queueCommand(
			_MotorCommand(
				lambda : self._mark(label),
				f"mark '{label}'"
			)
		)

	################################################################################
	#
	# goto(self, label)
	#
	################################################################################

	def goto(self, label):

		self._queueCommand(
			_MotorCommand(
				lambda : self._goto(label),
				f"go to '{label}'"
			)
		)

	################################################################################
	#
	# observe(self, observer)
	#
	################################################################################

	def observe(self, observer):

		self._observer = observer;

	################################################################################
	#
	# wait(self)
	#
	################################################################################

	def wait(self) -> int:

		# Blocks until motion stops (either because the target position has been
		# reached, or because a halt command has been issued (which is a case of
		# a new foreshortened target having been reached)). Returns the final
		# resting position of the motor.

		self._waitCompleteEvent.clear() # We're not complete, as we're waiting.

		self._motionCompleteEvent.wait() # Wait for motion to complete (to stop)
		pos = self._lastSteadyStatePosition 

		self._waitCompleteEvent.set() # We're done waiting, so the vent loop can continue.

		return pos

	################################################################################
	#
	# motionUpdateInterval(self, intervalSecs)
	#
	################################################################################

	def motionUpdateInterval(self, intervalSecs):

		self._queueCommand(
			_MotorCommand(
				lambda : self._motionInterval(intervalSecs),
				f"motion update interval '{intervalSecs}'"
			)
		)

	################################################################################
	#
	# idleUpdateInterval(self, intervalSecs)
	#
	################################################################################

	def idleUpdateInterval(self, intervalSecs):

		self._queueCommand(
			_MotorCommand(
				lambda : self._idleUpdateInterval(intervalSecs),
				f"idle update interval '{intervalSecs}'"
			)
		)

	################################################################################
	#
	# steppingStyle(self, steppingStyle)
	#
	################################################################################

	def steppingStyle(self, steppingStyle):

		self._queueCommand(
			_MotorCommand(
				lambda : self._steppingStyle(steppingStyle),
				f"idle update interval '{_renderStepping(steppingStyle)}'"
			)
		)

	################################################################################
	#
	# reverseMotion(self, reversed)
	#
	################################################################################

	def reverseMotion(self, reversed):

		self._queueCommand(
			_MotorCommand(
				lambda : self._reverseMotion(reversed),
				f"reverse motion {reversed}"
			)
		)

	################################################################################
	#
	# motionStepDelay(self, delay)
	#
	################################################################################

	def motionStepDelay(self, delaySecs):

		self._queueCommand(
			_MotorCommand(
				lambda: self._motionStepDelay(delaySecs),
				f"motion step delay {delaySecs}"
			)
		)

	####################################################################################
	#
	# start(self)
	#
	####################################################################################

	def start(self):

		if (self._running):
			raise NotImplementedError("Attempt to start() when already running.")

		self._running = True

		self._start()

	####################################################################################
	#
	# stop(self)
	#
	####################################################################################

	def stop(self):

		if (not self._running):
			raise NotImplementedError("Attempt to stop() when not running.")

		self._running = False

		self._stop()

	####################################################################################
	#
	# tryStart(self)
	#
	####################################################################################

	def tryStart(self) -> bool:

		success = not self._running

		if (success):
			self._start()
			self._running = True

		return success

	####################################################################################
	#
	# tryStop(self)
	#
	####################################################################################

	def tryStop(self) -> bool:

		success = self._running

		if (success):
			self._stop()
			self._running = False

		return success

	################################################################################
	#
	# run(self)
	#
	################################################################################

	def run(self):

		try:
			self._eventLoop()

		except KeyboardInterrupt:
			self._logger.debug("*** Interrupted.")

		finally:
			self._stepperMotor.release()
			self._logger.debug("Released motor.")
			self._motionCompleteEvent.set() # Motion is now complete.

	################################################################################
	#
	# _start(self)
	#
	################################################################################

	def _start(self):

		self._logger.info("Stepper motor controller starting...")

		self._future = self._threadPool.submit(self._eventLoop)

		self._logger.info("Stepper motor controller started.")

	################################################################################
	#
	# _stop(self)
	#
	################################################################################

	def _stop(self):

		self._logger.info("Stepper motor controller stopping...")

		self._looping = False

		while (not self._future.done()):
			self._logger.debug("Waiting for stepper motor controller to stop...")
			time.sleep(1)

		self._logger.info("Stepper motor controller stopped.")

	################################################################################
	#
	# _eventLoop(self)
	#
	################################################################################

	def _eventLoop(self):

		self._logger.debug(f"Starting eventLoop_()")

		self._motionCompleteEvent.set()

		# We handle both the receipt of incoming commands and instigating actual
		# motion in this event loop. This makes accessing state a little less complicated
		# as the commands are simply channelled here via a thread-safe command queue.
		#
		# Note that when there is no motion to be enacted, and no commands to execute,
		# we just block awaiting for something to appear in the command queue rather than
		# spin the CPU. Any further motion can only occur via a received command.

		prevMoving = (int(self._prevMotorPosition) != int(self._prevTargetMotorPosition))
		moving = (int(self._motorPosition) != int(self._targetMotorPosition))

		self._countdownTimer = self._idlingReportCountdownTimer

		while self._looping:

			if (not moving): # Not moving, so block on command queue rather than spin CPU.


				try:
					# Can block, which is fine, as there's no motion in progress.
					# We do however use a timeout as we still have the responsibility
					# of issuing positional/state reports regularly.

					command = self._commandQueue.get(timeout = self._idlingReportInterval)
					self._executeCommandSafely(command)

				except queue.Empty: # Timed out.
					# Just means there were no incoming commands and we got tired of waiting.
					pass

			else:
				# Motion is in progress, so keep it moving, but still look at the command
				# queue (non-blocking) as there could be a command to change the
				# motion that is in progress (e.g. "stop" that motion, or change it's
				# direction of motion towards a new target position, etc.).

				if (not self._commandQueue.empty()):
					command = self._commandQueue.get() # Will never block as we checked beforehand.
					self._executeCommandSafely(command)

				self._motorPosition += int(self._performMotionIncrement(
					int(self._targetMotorPosition), int(self._motorPosition)
				)) # If needed, move the motor a bit.

			if (self._targetIdlingReportInterval != self._idlingReportInterval):
				self._acceptNewIdlingReportingInterval()

			elif (self._targetMotionReportInterval != self._motionReportInterval):
				self._acceptNewMotionReportingInterval()

			# If motion is in progress, then our rate of reporting status
			# differs from that when there is no motion. Hence, we select
			# which countdown timer to use for reporting point-in-time
			# determination depending upon whether in motion or not.
			#
			# When comparing positions, cast to int to ensure that we are
			# actually doing an integer comparison, otherwise if it evaluates
			# to a floating point comparison, we may never appear to reach
			# the target position. All positions are notionally integral,
			# so ensure we treat them as such.

			moving = (int(self._motorPosition) != int(self._targetMotorPosition))

			if (not prevMoving and moving):

				self._motionCompleteEvent.clear() # Motion is now in progress, so not complete.

				self._motionReportCountdownTimer.restart()
				self._countdownTimer = self._motionReportCountdownTimer

			elif (prevMoving and not moving):

				# Motion is finished, we've reached our target. Ensure that the
				# final destination is reported and that power to the stepper
				# motor is released.

				self._onPositionUpdate(self._targetMotorPosition, self._motorPosition)
				self._stepperMotor.release() # Finished moving, so stop motor getting toasty.

				self._idlingReportCountdownTimer.restart()
				self._countdownTimer = self._idlingReportCountdownTimer

				# If client is calling wait() to retrieve the last steady-state position,
				# then give them access to it.

				self._waitCompleteEvent.wait() # Wait for caller to finishing waiting for completion.
				self._lastSteadyStatePosition = self._motorPosition # The item the waiter required.
				self._motionCompleteEvent.set() # Motion is now complete.

			elif (self._countdownTimer.hasExpired()): # Moving or not, report our position.

				self._onPositionUpdate(self._targetMotorPosition, self._motorPosition)
				self._countdownTimer.restart()

			self._prevMotorPosition = self._motorPosition
			self._prevTargetMotorPosition = self._targetMotorPosition

			prevMoving = moving

		self._logger.debug(f"Exiting eventLoop_()")

		return 0

	################################################################################
	#
	# _moveBy(self, steps)
	#
	################################################################################

	def _moveBy(self, steps):

		self._targetMotorPosition += steps

	################################################################################
	#
	# _moveTo(self, position)
	#
	################################################################################

	def _moveTo(self, position):

		self._targetMotorPosition = position

	################################################################################
	#
	# _halt(self)
	#
	################################################################################

	def _halt(self):

		self._targetMotorPosition = self._motorPosition

	################################################################################
	#
	# _mark(self, label)
	#
	################################################################################

	def _mark(self, label):

		self._markedPositions[label] = self._motorPosition

	################################################################################
	#
	# _goto(self, label)
	#
	################################################################################

	def _goto(self, label):

		if (not(label in self._markedPositions)):
			raise Exception(f"Undefined label '{label}'.")

		self._targetMotorPosition = self._markedPositions[label]

	################################################################################
	#
	# _motionReportInterval(self, intervalSecs)
	#
	################################################################################

	def _motionReportInterval(self, intervalSecs):

		self._targetMotionReportInterval = intervalSecs

	################################################################################
	#
	# _setIdleUpdateInterval(self, intervalSecs)
	#
	################################################################################

	def _setIdleUpdateInterval(self, intervalSecs):

		self._targetIdlingReportInterval = intervalSecs

	################################################################################
	#
	# _steppingStyle(self, steppingStyle)
	#
	################################################################################

	def _steppingStyle(self, steppingStyle):

		self._motorSteppingStyle = steppingStyle

	################################################################################
	#
	# _reverseMotion(self, reversed)
	#
	################################################################################

	def _reverseMotion(self, reversed):

		self._motorMotionReversed = reversed

	################################################################################
	#
	# _motionStepDelay(self, delay)
	#
	################################################################################

	def _motionStepDelay(self, delaySecs):

		raise Exception('Motion speed control not yet implemented.')

	################################################################################
	#
	# _queueCommand(self, command)
	#
	################################################################################

	def _queueCommand(self, command):

		self._commandQueue.put(command);
		self._logger.debug(f"Command: {command} queued.")

	################################################################################
	#
	# _executeCommandSafely(self, command)
	#
	################################################################################

	def _executeCommandSafely(self, command):

		try:
			command.execute()
			self._logger.info(f"Command: {command} executed.")

		except Exception as ex:
			self._logger.error(f"Error executing {command}: {ex}.")

	################################################################################
	#
	# _onPositionUpdate(self, targetPosition, actualPosition)
	#
	################################################################################

	def _onPositionUpdate(self, targetPosition, actualPosition):

		try:
			if (self._observer):
				self._observer(targetPosition, actualPosition)

		except Exception as ex:
			self._logger.warning(f"Position observer misbehaved: {ex}")

		except:
			self._logger.warning(f"Position observer misbehaved.")

	################################################################################
	#
	# _performMotionIncrement(self, targetPosition, currentPosition)
	#
	################################################################################

	def _performMotionIncrement(self, targetPosition, currentPosition):

		# We're only going to move one step, but we need to work out
		# in which direction we need to move. 

		logicalChange = 0

		noOfStepsRemaining = targetPosition - currentPosition

		if (noOfStepsRemaining != 0):  # Is there movement required?

			try:

				backwards = (noOfStepsRemaining < 0)  # The logical direction (user perspective).	
				absSteps = abs(noOfStepsRemaining)

				# If the number of steps is negative, then we are going backwards,
				# unless the motion has been set as reversed. But we keep separate
				# the notion of logical direction (the user perspective) versus the
				# internal notion of direction.

				if (backwards):
					logicalChange = -1
					actuallyBackwards = not self._motorMotionReversed
				else:
					logicalChange = 1
					actuallyBackwards = self._motorMotionReversed

				motionDirection = stepper.BACKWARD if actuallyBackwards else stepper.FORWARD

				# Just cycling one step right now, in the determined direction.

				self._stepperMotor.onestep(direction = motionDirection, style = self._motorSteppingStyle)    

			finally: # Never leave the stepper motor drawing current and getting toasty.

				if (currentPosition == targetPosition):
					self._stepperMotor.release()
					self._logger.debug("Released motor.")

		return logicalChange

	################################################################################
	#
	# _acceptNewIdlingReportingInterval(self)
	#
	################################################################################

	def _acceptNewIdlingReportingInterval(self):

		self._logger.debug(f"New (static) update interval, changed from {self._idlingReportInterval} to {self._targetIdlingReportInterval}.")

		self._idlingReportInterval = self._targetIdlingReportInterval
		self._idlingReportCountdownTimer.period(self._idlingReportInterval)

		self._logger.debug("Publishing position (after change to idle state) reporting interval.")

		self._onPositionUpdate(self._targetMotorPosition, self._motorPosition)
		self._idlingReportCountdownTimer.restart()

	################################################################################
	#
	# _acceptNewMotionReportingInterval(self)
	#
	################################################################################

	def _acceptNewMotionReportingInterval(self):

		self._logger.debug(f"New (motion) update interval, changed from {self._motionReportInterval} to {self._targetMotionReportInterval}.")

		self._motionReportInterval = self._targetMotionReportInterval
		self._motionReportCountdownTimer.period(self._motionReportInterval)

		self._logger.debug("Publishing position (after change to motion) state reporting interval).")

		self._onPositionUpdate(self._targetMotorPosition, self._motorPosition)
		self._motionReportCountdownTimer.restart()

	################################################################################
	#
	# _render(self, steppingStyle)
	#
	################################################################################

	def _renderStepping(self, steppingStyle):

		str = '?'

		if (steppingStyle == stepper.SINGLE):
			str = "single"

		elif (steppingStyle == stepper.DOUBLE):
			str = "double"

		elif (steppingStyle == stepper.INTERLEAVE):
			str = "interleave"

		elif (steppingStyle == stepper.MICROSTEP):
			str = "microstep"

		return str

	################################################################################
	#
	# __del__(self)
	#
	################################################################################

	def __del__(self):

		if (self._running):
			self._stop()
			self._running = False


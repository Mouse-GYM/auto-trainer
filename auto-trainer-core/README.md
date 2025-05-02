# Autotrainer - Core

This is the base module for functions and objects that used across most or all modules and applications.

Major Elements
* Observable object implementation
* Common Protocols used to bridge different modules
* Event notification hub
* Enhanced multiprocessing shared array behavior
* General "project" and animal subject data and management
* Fundamental data analysis operations that may be used ro replay/reprocess data, not just in live capture
* System configuration reading and persistence
* Misc utilities
  * Performance monitoring wrappers
  * Queue extensions

### Future Work
Trigger manager and event manager are specific implementations of general notification hub/bus.  This should
be improved.

The event manager should allow for plugin registration for the various outputs.  It is currently hard-coded
for the logger and file.  These should be independently enabled, as well as support addition of other outputs.
OTel integration is a known requirement that needs to be implemented.  The `autotrainer.api` module (not
part of this repository) also needs to be able to register for events.

The Project class and functionality is largely geared towards the creation of projects, knowing where to save
data and created those folders and files where necessary.  It should be improved to make it easier to use as 
a reader for tools that need to be aware of those folders and files, but never create them.  This will be used
by the management console to read information without needed to burden the acquisition application directly.

System configuration files have been updated to use YAML tags for typing and with a new structure that better
aligns to the subsystems and their properties.  There is a still a step to separate a) device values that
are unlikely to change over time (e.g., hardware ports), b) values related to application that can change
between sessions, but would not be considered "training" variables and c) training variables that users
are likely to change regularly and in some cases may be changed by hand.

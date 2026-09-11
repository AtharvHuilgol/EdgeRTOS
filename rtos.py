"""
RTOS Compatibility Alias for EdgeRTOS.
Allows `import rtos` or `from rtos import ...` seamlessly.
"""

from edgertos import *
from edgertos import __doc__ as _doc
__doc__ = _doc

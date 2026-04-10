
import warnings

import autotrainer.core.user_preferences as new_user_prefs

warnings.warn(f"{__name__} is deprecated, please use {new_user_prefs.__name__}",
              DeprecationWarning, stacklevel=2)

globals().update(new_user_prefs.__dict__)

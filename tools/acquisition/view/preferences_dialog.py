from PySide6.QtWidgets import QDialog, QDialogButtonBox, QVBoxLayout

from tools.acquisition.model.user_preferences import UserPreferences
from tools.acquisition.view.preferences_content import PreferencesContent


class PreferencesDialog(QDialog):
    def __init__(self, preferences: UserPreferences, parent=None):
        super(PreferencesDialog, self).__init__(parent)

        self.setWindowTitle("Preferences")
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)

        buttons = QDialogButtonBox.StandardButton.Ok

        self.buttonBox = QDialogButtonBox(buttons)
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)

        self.layout = QVBoxLayout()
        self.layout.addWidget(PreferencesContent(preferences))
        self.layout.addWidget(self.buttonBox)

        self.setLayout(self.layout)

"""Microsoft 365 via Microsoft Graph, on behalf of a signed-in person (OAuth 2.0
delegated access): files (SharePoint, OneDrive) and the cells of their Excel workbooks,
Outlook mail and calendar, Teams,
OneNote, and the organization's directory (read; licences, accounts enabled and group
members written).

`auth` signs the person in, `scopes` names the permissions of each surface, and one
client per surface spends the access token."""

from . import auth, scopes
from .auth import Grant, MicrosoftAuthError, MicrosoftGrantExpired
from .calendar import CalendarClient
from .directory import DirectoryClient
from .files import FilesClient
from .mail import MailClient
from .onenote import OneNoteClient
from .teams import TeamsClient
from .workbook import WorkbookClient

__all__ = ["auth", "scopes", "FilesClient", "MailClient", "CalendarClient", "TeamsClient",
           "OneNoteClient", "DirectoryClient", "WorkbookClient", "Grant", "MicrosoftAuthError", "MicrosoftGrantExpired"]

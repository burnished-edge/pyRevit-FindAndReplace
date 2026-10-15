#! ipy3
# Keep the Python runtime alive so modeless events and imports do not get destroyed
__persistentengine__ = True

import clr
import re

clr.AddReference('System')
clr.AddReference('System.Windows.Forms')
clr.AddReference('PresentationCore')
clr.AddReference('PresentationFramework')
clr.AddReference('WindowsBase')

from System import Action, TimeSpan
from System.Collections.ObjectModel import ObservableCollection
from System.Collections.Generic import List
from System.Windows.Controls import TextBlock
from System.Windows.Documents import Run
from System.Windows import FontWeights, VerticalAlignment, TextWrapping
from System.Windows.Threading import DispatcherTimer

from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent
from pyrevit.forms import WPFWindow
from pyrevit import DB, revit, forms, HOST_APP


class WindowActionHandler(IExternalEventHandler):
    """Safely executes all Revit API calls on the Revit Main Thread"""
    def __init__(self, window_instance):
        self.window = window_instance
        self.action = None
        
    def Execute(self, app):
        try:
            if self.action == "refresh":
                self.window.execute_refresh()
            elif self.action == "apply":
                self.window.execute_apply()
            elif self.action == "select":
                self.window.execute_select()
            elif self.action == "show":
                self.window.execute_show()
        except Exception as e:
            print("External Event Error: " + str(e))
            
    def GetName(self):
        return "FindReplaceUniversalHandler"


class FindReplaceWindow(WPFWindow):
    
    class ElementRow(object):
        """Data binding model for the WPF DataGrid"""
        def __init__(self, element, ref_val, original_val, param_to_set):
            self.Element = element
            self.ParamToSet = param_to_set
            self.Reference = str(ref_val) if ref_val is not None else ""
            self.OriginalName = str(original_val) if original_val is not None else ""
            self._newName = self.OriginalName
            self._formattedName = None
            self._include = False

        @property
        def NewName(self):
            return self._newName

        @NewName.setter
        def NewName(self, value):
            self._newName = value

        @property
        def FormattedNewName(self):
            return self._formattedName

        @FormattedNewName.setter
        def FormattedNewName(self, value):
            self._formattedName = value

        @property
        def Include(self):
            return self._include

        @Include.setter
        def Include(self, value):
            self._include = bool(value)

    def __init__(self, xaml_file_name):
        WPFWindow.__init__(self, xaml_file_name)
        
        self.all_rows = []
        self.rows_to_process = []
        self.selected_element_id = None
        self.current_category = "Sheet Names" 
        
        # Debounce timer for smooth typing
        self.debounce_timer = DispatcherTimer()
        self.debounce_timer.Interval = TimeSpan.FromMilliseconds(200)
        self.debounce_timer.Tick += self.on_debounce_tick

        self.action_handler = WindowActionHandler(self)
        self.ext_event = ExternalEvent.Create(self.action_handler)
        
        self.execute_refresh()

    def _get_doc(self):
        try:
            from pyrevit import revit
            return revit.doc
        except Exception:
            return HOST_APP.doc

    def _get_uidoc(self):
        try:
            from pyrevit import revit
            return revit.uidoc
        except Exception:
            return HOST_APP.uidoc

    # ==========================================================
    # SAFE REVIT API EXECUTION METHODS 
    # ==========================================================
    def execute_refresh(self):
        from pyrevit import DB
        doc = self._get_doc()
        temp_rows = []
        category = self.current_category
        
        if category == "Sheet Names":
            for sheet in DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Sheets).WhereElementIsNotElementType():
                temp_rows.append(self.ElementRow(sheet, sheet.SheetNumber, sheet.Name, DB.BuiltInParameter.SHEET_NAME))
                
        elif category == "Sheet Numbers":
            for sheet in DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Sheets).WhereElementIsNotElementType():
                temp_rows.append(self.ElementRow(sheet, sheet.Name, sheet.SheetNumber, DB.BuiltInParameter.SHEET_NUMBER))
                
        elif category == "Room Names":
            for room in DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Rooms).WhereElementIsNotElementType():
                r_num = room.get_Parameter(DB.BuiltInParameter.ROOM_NUMBER)
                r_num_val = r_num.AsString() if r_num else ""
                r_name = room.get_Parameter(DB.BuiltInParameter.ROOM_NAME)
                r_name_val = r_name.AsString() if r_name else ""
                temp_rows.append(self.ElementRow(room, r_num_val, r_name_val, DB.BuiltInParameter.ROOM_NAME))

        elif category == "Room Numbers":
            for room in DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Rooms).WhereElementIsNotElementType():
                r_num = room.get_Parameter(DB.BuiltInParameter.ROOM_NUMBER)
                r_num_val = r_num.AsString() if r_num else ""
                r_name = room.get_Parameter(DB.BuiltInParameter.ROOM_NAME)
                r_name_val = r_name.AsString() if r_name else ""
                temp_rows.append(self.ElementRow(room, r_name_val, r_num_val, DB.BuiltInParameter.ROOM_NUMBER))

        elif category == "View Names":
            for view in DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Views).WhereElementIsNotElementType():
                if not view.IsTemplate:
                    temp_rows.append(self.ElementRow(view, view.ViewType, view.Name, DB.BuiltInParameter.VIEW_NAME))

        elif category == "View Titles":
            for view in DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Views).WhereElementIsNotElementType():
                if not view.IsTemplate:
                    title_param = view.get_Parameter(DB.BuiltInParameter.VIEW_DESCRIPTION)
                    title_val = title_param.AsString() if title_param else ""
                    temp_rows.append(self.ElementRow(view, view.Name, title_val, DB.BuiltInParameter.VIEW_DESCRIPTION))

        elif category == "Materials":
            for mat in DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Materials):
                temp_rows.append(self.ElementRow(mat, mat.MaterialClass, mat.Name, "ELEMENT_NAME"))

        elif category == "Text Notes":
            for text_note in DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_TextNotes).WhereElementIsNotElementType():
                view_name = doc.GetElement(text_note.OwnerViewId).Name if text_note.OwnerViewId != DB.ElementId.InvalidElementId else "Unknown View"
                temp_rows.append(self.ElementRow(text_note, view_name, text_note.Text, "TEXT_NOTE_TEXT"))

        elif category == "Levels":
            for level in DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Levels).WhereElementIsNotElementType():
                temp_rows.append(self.ElementRow(level, round(level.Elevation, 2), level.Name, "ELEMENT_NAME"))

        self.all_rows = temp_rows
        self.Dispatcher.Invoke(Action(self.update_preview))

    def execute_select(self):
        from pyrevit import DB
        uidoc = self._get_uidoc()
        if self.selected_element_id:
            try:
                id_list = List[DB.ElementId]()
                id_list.Add(self.selected_element_id)
                uidoc.Selection.SetElementIds(id_list)
            except Exception:
                pass 

    def execute_show(self):
        uidoc = self._get_uidoc()
        if self.selected_element_id:
            try:
                uidoc.ShowElements(self.selected_element_id)
            except Exception:
                pass 

    def execute_apply(self):
        from pyrevit import revit, forms
        with revit.Transaction("Find and Replace"):
            success_count = 0
            for row in self.rows_to_process:
                try:
                    if row.ParamToSet == "ELEMENT_NAME":
                        row.Element.Name = row.NewName
                        success_count += 1
                    elif row.ParamToSet == "TEXT_NOTE_TEXT":
                        row.Element.Text = row.NewName
                        success_count += 1
                    else:
                        param = row.Element.get_Parameter(row.ParamToSet)
                        if param and not param.IsReadOnly:
                            param.Set(row.NewName)
                            success_count += 1
                except Exception as e:
                    print("Failed to rename {} : {}".format(row.OriginalName, str(e)))
        
        forms.alert("Successfully updated {} elements.".format(success_count))
        self.execute_refresh()

    # ==========================================================
    # STANDARD UI METHODS (Run on WPF Thread)
    # ==========================================================
    def update_preview(self):
        find_text = self.txtFind.Text
        replace_text = self.txtReplace.Text or ""
        prefix = self.txtPrefix.Text or ""
        suffix = self.txtSuffix.Text or ""
        capitalize = self.chkCapitalize.IsChecked
        case_sensitive = self.chkCaseSensitive.IsChecked

        display_list = ObservableCollection[object]()

        def format_case(text):
            return text.upper() if capitalize else text

        # Pre-compile regex once per preview update rather than once per row
        pattern = None
        if find_text:
            flags = 0 if case_sensitive else re.IGNORECASE
            pattern = re.compile(re.escape(find_text), flags)

        for row in self.all_rows:
            orig = row.OriginalName
            row.Include = False 
            new_val = orig

            # Live Filtering
            if find_text:
                if case_sensitive:
                    if find_text not in orig:
                        continue 
                else:
                    if find_text.lower() not in orig.lower():
                        continue 
            
            # Rich Text Preview
            tb = TextBlock()
            tb.VerticalAlignment = VerticalAlignment.Center
            tb.TextWrapping = TextWrapping.Wrap
            
            if prefix:
                r = Run(format_case(prefix))
                r.FontWeight = FontWeights.Bold
                tb.Inlines.Add(r)
                row.Include = True
                
            if pattern:
                last_idx = 0
                for match in pattern.finditer(orig):
                    row.Include = True
                    
                    before_text = orig[last_idx:match.start()]
                    if before_text:
                        tb.Inlines.Add(Run(format_case(before_text)))
                    
                    if replace_text:
                        r = Run(format_case(replace_text))
                        r.FontWeight = FontWeights.Bold
                        tb.Inlines.Add(r)
                    
                    last_idx = match.end()
                    
                after_text = orig[last_idx:]
                if after_text:
                    tb.Inlines.Add(Run(format_case(after_text)))
                    
                new_val = pattern.sub(replace_text, orig)
            else:
                tb.Inlines.Add(Run(format_case(orig)))
                
            if suffix:
                r = Run(format_case(suffix))
                r.FontWeight = FontWeights.Bold
                tb.Inlines.Add(r)
                row.Include = True
                
            if capitalize and new_val != new_val.upper():
                row.Include = True

            row.NewName = format_case(prefix + new_val + suffix)
            row.FormattedNewName = tb 
            display_list.Add(row)

        self.dataGrid.ItemsSource = display_list

    # ==========================================================
    # UI EVENT HANDLERS
    # ==========================================================
    def CategoryChanged(self, sender, args):
        if sender.IsChecked: 
            self.current_category = sender.Content.ToString()
            if hasattr(self, 'action_handler'): 
                self.action_handler.action = "refresh"
                self.ext_event.Raise()

    def InputChanged(self, sender, args):
        if hasattr(self, 'debounce_timer'):
            self.debounce_timer.Stop()
            self.debounce_timer.Start()

    def on_debounce_tick(self, sender, args):
        self.debounce_timer.Stop()
        if hasattr(self, 'all_rows'):
            self.update_preview()
            
    def SelectElement(self, sender, args):
        selected_row = self.dataGrid.SelectedItem
        if selected_row:
            self.selected_element_id = selected_row.Element.Id
            if hasattr(self, 'action_handler'):
                self.action_handler.action = "select"
                self.ext_event.Raise()

    def ShowElement(self, sender, args):
        selected_row = self.dataGrid.SelectedItem
        if selected_row:
            self.selected_element_id = selected_row.Element.Id
            if hasattr(self, 'action_handler'):
                self.action_handler.action = "show"
                self.ext_event.Raise()

    def ApplyChanges(self, sender, args):
        from pyrevit import forms
        # Force any pending debounce updates to finish first
        if hasattr(self, 'debounce_timer') and self.debounce_timer.IsEnabled:
            self.debounce_timer.Stop()
            self.update_preview()

        # Commit any active cell and row checkbox edits
        self.dataGrid.CommitEdit()
        self.dataGrid.CommitEdit()
        
        self.rows_to_process = [row for row in self.dataGrid.ItemsSource if row.Include is True]
        
        if not self.rows_to_process:
            forms.alert("No elements selected to change.")
            return

        if hasattr(self, 'action_handler'):
            self.action_handler.action = "apply"
            self.ext_event.Raise()


__window__ = FindReplaceWindow('ui.xaml')
__window__.Show()

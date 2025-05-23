from ErrorLog.WriteFileLog import Logger
from Modules.CustomLoader import CustomLoader
from Modules.EventBlocker import EventBlocker
from Modules.custum_retry_dialog import CustomRetryBox
from Helper.custom_message_box import CustomMessageBox
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QDialog, QFrame,
    QTableView, QAbstractItemView, QStyledItemDelegate, QHeaderView, QLineEdit, QComboBox
)
from PyQt5.QtCore import Qt, QSize, QTimer, QThread, pyqtSignal
from PyQt5.QtGui import QIcon, QFont, QFontDatabase, QPixmap, QStandardItemModel, QStandardItem, QMovie
from Helper.msgboxEncodeDecode import CustomMessageBox as CustomMessageBoxReason
from Modules.keyb import CustomKeyboard
from Services import InwardService, RFID_Scanner, EncodingService, RegistrationService
from Services.ConveyorServiceDC import ConveyorService
import sys
import os
import threading
from collections import Counter
import uuid
import time
import json
import SharedData
import uuid
from UI.NetworkCheckerSingleton import NetworkStatusCheckerSingleton
from Utility import Utility


current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, '..'))
sys.path.insert(0, root_dir)
logger_instance = Logger()
logger = logger_instance.get_logger()

#start Added by imran dated 23-may-2025
sys.setrecursionlimit(1000)
if hasattr(threading, 'stack_size'):
    threading.stack_size(2*1024*1024)
    
class SafeQThread(QThread):
  
    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self._lock = threading.RLock()
        
    def stop(self):       
        with self._lock:
            self._running = False
        if not self.wait(500):
            logger.warning(f"Thread {self.__class__.__name__} didn't stop gracefully")
            self.terminate()
            
    def __del__(self):      
        self.stop()
 
class NoBorderDelegate(QStyledItemDelegate):
    try:
        def paint(self, painter, option, index):
            painter.save()
            painter.setPen(Qt.NoPen)
            super().paint(painter, option, index)
            painter.restore()
    except Exception as ex:
        logger.error(ex, exc_info=True)


class ScanThread(SafeQThread):
    scan_finished = pyqtSignal(list)
    error_occurred = pyqtSignal(str)
    #clear_thread= pyqtSignal()

    def run(self):
        try:
            ean_list = RFID_Scanner.get_rfid_ean_list()
            if ean_list:
                self.scan_finished.emit(ean_list)
                #self.clear_thread.emit()
            else:
                self.error_occurred.emit("No Tags Found")
        except Exception as ex:
            self.error_occurred.emit("Error occured")
            logger.error(ex, exc_info=True)
            pass
        
class ConveyorOperationThread(SafeQThread):
    #Base class for conveyor operations
    operation_complete = pyqtSignal(int)
    operation_failed = pyqtSignal(str)
    timeout_occurred = pyqtSignal()
    
    def __init__(self, conveyor, command_name):
        super().__init__()
        self.conveyor = conveyor
        self.command_name = command_name
        
    def run(self):
        try:
            self._running = True
            while self._running:
                result = self._execute_operation()
                
                if result == 171:
                    self.operation_failed.emit("Please retry")
                    break
                elif result in (4, 5, 0):  # Success codes
                    self.operation_complete.emit(result)
                    break
                elif result == 777:
                    self.timeout_occurred.emit()
                    break
                    
                time.sleep(0.1)  # Prevent busy waiting
                
        except Exception as ex:
            self.operation_failed.emit(f"{self.command_name} failed: {str(ex)}")
            logger.error(ex, exc_info=True)
            
class AcceptConveyorThread(ConveyorOperationThread):
    def _execute_operation(self):
        return self.conveyor.accept_conveyor()

class RejectConveyorThread(ConveyorOperationThread):
    def _execute_operation(self):
        return self.conveyor.reject_conveyor()

    def _execute_operation(self):
        raise NotImplementedError()        

class StartConveyorThread(ConveyorOperationThread):
    start_scan = pyqtSignal(int)
    door_emergency = pyqtSignal(str)
    remove_box = pyqtSignal(str)
    no_box = pyqtSignal(str)
    door_cleared = pyqtSignal()
    
    def _execute_operation(self):
        result = self.conveyor.start_conveyor()
        
        if result == 3:  # Door emergency case
            self.door_emergency.emit("Please remove the object from the gate")
            while self._running:
                emergency_result = self.conveyor.call_after_door_emergency()
                if emergency_result == 0:
                    self.door_cleared.emit()
                    time.sleep(0.1)
                    self.start_scan.emit(0)
                    break
                    
        return result

class EncodeThread(SafeQThread):
    encode_finished = pyqtSignal(list)
    error_occurred = pyqtSignal(str)
    
    def __init__(self, ean, scan_result, parent=None):
        super().__init__(parent)
        self.ean = ean
        self.scan_result = scan_result
        
    def run(self):
        try:
            encoding_ean_list = EncodingService.start_encoding(
                self.ean, self.scan_result)
                
            if encoding_ean_list is None:
                self.error_occurred.emit(
                    "There was a problem with encoding tags. Please try again.")
                return

            self.encode_finished.emit(encoding_ean_list)
            
        except Exception as ex:
            self.error_occurred.emit(f"Encoding error: {str(ex)}")
            logger.error(ex, exc_info=True)


class accept_conveyor(QThread):

    accept_button = pyqtSignal(int)
    timeout_signal = pyqtSignal()
    init_failed = pyqtSignal(str)
    clear_thread = pyqtSignal()

    def __init__(self, conveyer):
        super().__init__()
        self.conveyor = conveyer       
        self.running = False

    def run(self):
        try:
            self.running = True         
            while self.running:
                result = self.conveyor.accept_conveyor()
                if result == 171:
                    self.init_failed.emit("please retry")
                    self.clear_thread.emit()                   
                    break 
                if result == 4:
                   
                    self.accept_button.emit(0)
                    self.clear_thread.emit()                  
                    break 
                elif result == 777:
                    print("Timeout occurred")
                    self.timeout_signal.emit()
                    self.clear_thread.emit()                  
                    break
        except Exception as ex:
            logger.error(ex, exc_info=True)
            pass

    def stop(self):
        self.running = False


class reject_conveyor(QThread):

    reject_button = pyqtSignal(int)
    timeout_signal = pyqtSignal()
    init_failed = pyqtSignal(str)
    clear_thread= pyqtSignal()

    def __init__(self, conveyer):
        super().__init__()
        self.conveyor = conveyer
        self.running = True

    def run(self):
        try:           
            while self.running:
                result = self.conveyor.reject_conveyor()
                if result == 171:
                    self.init_failed.emit("please retry")
                    self.clear_thread.emit()                   
                    break
                if result == 5:                 
                    self.reject_button.emit(0)
                    self.clear_thread.emit()
                    break
                    
                elif result == 777:
                    print("Timeout occurred")
                    self.timeout_signal.emit()
                    self.clear_thread.emit()                   
                    break
        except Exception as ex:
            logger.error(ex, exc_info=True)
            pass

    def stop(self):
        self.running = False


class start_conveyor(QThread):

    start_scan = pyqtSignal(int)
    door_emergency = pyqtSignal(str)
    remove_box = pyqtSignal(str)
    no_box = pyqtSignal(str)
    timeout_signal = pyqtSignal()
    door_cleared = pyqtSignal()
    init_failed = pyqtSignal(str)
    clear_thread= pyqtSignal()

    def __init__(self, conveyer):
        super().__init__()
        self.conveyor = conveyer
        self.running = True

    def run(self):
        try:
            result = 6
            start_time = time.time()
            while self.running:
                if result != 3 or result != 0:
                    result = self.conveyor.start_conveyor()
                if result == 171:
                    self.init_failed.emit("please retry")
                    self.clear_thread.emit()                   
                    break
                if result == 1:
                    self.remove_box.emit("Please remove the box from ending")
                    self.clear_thread.emit()                   
                    break
                elif result == 2:
                    self.no_box.emit("No box place at the starting")
                    self.clear_thread.emit()                  
                    break
                elif result == 3:
                    self.door_emergency.emit(
                        "Please remove the object from the gate")
                    while self.running:
                        emergency_result = self.conveyor.call_after_door_emergency()
                        if emergency_result == 0:
                            self.door_cleared.emit()
                            time.sleep(0.1)
                            self.start_scan.emit(0)
                            self.clear_thread.emit()                           
                            break
                elif result == 777:
                    print("Timeout occurred")
                    self.timeout_signal.emit()
                    self.clear_thread.emit()                   
                    break
                elif result == 0:
                    self.start_scan.emit(0)
                    self.clear_thread.emit()                  
                    break

        except Exception as ex:
            logger.error(ex, exc_info=True)
            pass

    def stop(self):
        self.running = False



class MainWindowEncode(QWidget):

    def __init__(self):        
            super().__init__()           
            self._active_threads = []  
            self._active_timers = []
            self.saved_reason_id = None
            font_id = QFontDatabase.addApplicationFont(
                "CustomFont/jio_type_bold.TTF")
            font_families = QFontDatabase.applicationFontFamilies(font_id)
            if font_families:
                custom_font = font_families[0]
                QApplication.setFont(QFont(custom_font))
            from AppConfiguration import Configuration
            self.config = Configuration()
            self.conveyer = ConveyorService()
            self.scan_result = []
            self.back_click = False
            self.tag_for_encoding = []
            self.scan_id = str(uuid.uuid4())
            self.called_from_conveyor = False
    
    def _setup_ui(self):
        """Initialize the user interface"""
        self.setWindowTitle("Encode")
        self.setGeometry(0, 0, 800, 480)
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setStyleSheet("background-color: #FFFFFF;")
        
        # Load custom font
        font_id = QFontDatabase.addApplicationFont("CustomFont/jio_type_bold.TTF")
        if font_families := QFontDatabase.applicationFontFamilies(font_id):
            QApplication.setFont(QFont(font_families[0]))
            
            
        self.setWindowTitle("Encode")
        self.setGeometry(0, 0, 800, 480)
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setStyleSheet("background-color: #FFFFFF;")
            # self.center()

            # Main layout
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

            # Header layout
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(25, 0,
                                             10, 0)

            # Back Button
        self.back_button = QPushButton()
        self.back_icon = QIcon("icon/back.png")
        self.back_button.setIcon(self.back_icon)
        self.back_button.setIconSize(
                QSize(38, 38))
        self.back_button.setStyleSheet("border:none;")
        self.back_button.clicked.connect(self.handle_back_button)

            # Title Label
        title_label = QLabel("Encode Tags")
        title_label.setStyleSheet(
                f"color: white; font-size:18px; font-weight: bold;")

            # Logo
        logo_label = QLabel()
        logo_pixmap = QPixmap(
                "images/app-icon_white.png").scaled(SharedData.HEADER_LOGO_WIDTH, SharedData.HEADER_LOGO_HEIGHT, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        logo_label.setPixmap(logo_pixmap)
        logo_label.setFixedSize(
                SharedData.HEADER_LOGO_WIDTH, SharedData.HEADER_LOGO_HEIGHT)
        logo_label.setAlignment(Qt.AlignJustify)

            # Web Icon
        self.globe_label = QLabel()
        self.globe_pixmap_online = QPixmap(
                "images/globe_online.png").scaled(24, 24, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.globe_pixmap_offline = QPixmap(
                "images/globe_offline.png").scaled(24, 24, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.globe_pixmap = QPixmap("images/globe_online.png").scaled(24, 24, Qt.KeepAspectRatio,
                                                                          Qt.SmoothTransformation)  # Replace with actual path
        self.globe_label.setPixmap(self.globe_pixmap)
        self.globe_label.setFixedSize(
                24, 24)
        self.globe_label.setAlignment(Qt.AlignCenter)

        self.network_checker = NetworkStatusCheckerSingleton.get_instance()

            # Connect signals to slots
        self.network_checker.online.connect(self.online)
        self.network_checker.offline.connect(self.offline)

            # Home Icon
        home_label = QLabel()
        home_pixmap = QPixmap("icon/home.png").scaled(
                38, 38,
                Qt.KeepAspectRatio, Qt.SmoothTransformation)
        home_label.setPixmap(home_pixmap)
        home_label.setFixedSize(38, 38)
        home_label.setAlignment(Qt.AlignCenter)
            # Change cursor to a hand pointer
        home_label.setCursor(Qt.PointingHandCursor)
        home_label.mousePressEvent = self.handle_back_button

            # Add widgets to header layout
        header_layout.addWidget(self.back_button)
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        header_layout.addWidget(logo_label, alignment=Qt.AlignCenter)
        header_layout.addStretch()
        header_layout.addWidget(self.globe_label)
        header_layout.addWidget(home_label)

            # Set header widget
        header_widget = QWidget()
        header_widget.setFixedHeight(
                SharedData.HEADER_HEIGHT)
        header_widget.setLayout(header_layout)
        header_widget.setStyleSheet("background-color: #3e0084;")
        main_layout.addWidget(header_widget)

            # Control Buttons Layout
        self.wide_layout = QHBoxLayout()
        self.wide_layout.setContentsMargins(0, 0, 20, 0)
        control_layout = QHBoxLayout()
        control_layout.setContentsMargins(0, 5, 0, 0)
        control_layout.setSpacing(0)

        self.scan_label = QLabel("Scan EAN")
        self.scan_label.setStyleSheet(f"""
                    color: black;
                    font-size: 20px;
                    font-weight: bold;
                """)
        control_layout.setSpacing(10)

        self.textbox = QLineEdit(self)
            # self.textbox.setValidator(QIntValidator)
        self.textbox.setMaxLength(13)
        self.textbox.setMinimumWidth(250)
        self.textbox.setStyleSheet(f"""
            QLineEdit {{
                border: 1px solid #cccccc;
                border-radius: 10px;  
                padding: 5px;
                background: lightgray;
            }}
            """)
        self.textbox.mousePressEvent = lambda event: self.on_icon_click(self.textbox,
                                                                            event)
        control_layout.setSpacing(10)
        QTimer.singleShot(0, lambda: self.textbox.setFocus())

            # SCAN QUANTITY CHEKER
            # self.scan_qty = QLabel("Enter Qty")
            # self.scan_qty.setStyleSheet(
            #     "color: black; font-size: 20px; font-weight: bold;")
            # control_layout.setSpacing(10)

            # self.quantity = QLineEdit(self)
            # # self.textbox.setValidator(QIntValidator)
            # self.quantity.setMaxLength(5)
            # self.quantity.setMinimumWidth(250)
            # self.quantity.setStyleSheet("""
            # QLineEdit {
            #     border: 1px solid #cccccc;
            #     border-radius: 10px;
            #     padding: 5px;
            #     background: lightgray;
            # }
            # """)
            # self.quantity.mousePressEvent = lambda event: self.on_icon_click(self.quantity,
            #                                                                  event)

            # DC Code Label
        data = RegistrationService.fetch_dc_parentchild_details()
        self.dc_code_label = QComboBox(self)
        self.dc_code_label.setStyleSheet(f"""
                QComboBox {{
                background-color: lightgray;    /* Background color */
                    border: none;    /* Border color */
                    border-radius: 10px;          /* Rounded corners */
                    padding: 6px 15px;                 /* Padding inside the box */
                    font: 15px 'Segoe UI';        /* Font and size */
                    color: #000000;               /* Text color */ 
                    width : 150px;
                    font-weight: bold;
                    margin: 10px 0px;
            }}
            QComboBox::drop-down {{
                border: none;
                width: 20px;
                border-top-right-radius: 10px;  
                border-bottom-right-radius: 10px;  
                color: #000000;
            }}
            QComboBox::down-arrow {{
                image: url(images/down.png); 
                width: 16px;
                height: 16px;
                margin-right: 8px;
                background-color: lightgray;
            }}
             QComboBox QAbstractItemView {{
                    background-color: #ffffff;
                    border: none;
                    selection-background-color: #3399ff;
                    selection-color: #ffffff;
                }}
        """)

        for dc_id, dc_name in data.items():
                self.dc_code_label.addItem(dc_name, dc_id)
        self.dc_code_label.currentIndexChanged.connect(
                self.on_dc_code_changed)
        self.set_initial_selection()

        self.encode_hoz_layout = QHBoxLayout()
        self.encode_hoz_layout.setContentsMargins(10, 5, 0, 0)
        self.total_qty_label = QLabel("Total items : 0")
        self.total_qty_label.setStyleSheet(
                f"color: black; font-size: 18px; font-weight: bold;")
        self.encode_hoz_layout.setSpacing(10)

        self.acept = QHBoxLayout()
        self.acept.setContentsMargins(10, 5, 0, 0)
        self.total_qty_encode = QLabel("Total items : 0")
        self.total_qty_encode.setStyleSheet(
                f"color: black; font-size: 18px; font-weight: bold;")
        self.acept.setSpacing(10)

        self.accept_button = QPushButton("Accept")
        self.accept_button.setFixedSize(
                130, 40)
        self.accept_button.setStyleSheet(f"""
            QPushButton {{
                background-color: #3e0084; color: white;
                font-size: 18px; font-weight: bold;
                padding: 4px;
                border-radius: 17px;

            }}
            QPushButton:pressed {{
                background-color: #5D1299;
            }}
        """)
            # self.accept_button.clicked.connect(self.accept_conveyor)
        self.reject_button = QPushButton("Reject")
        self.reject_button.setFixedSize(130, 40)
        self.reject_button.setStyleSheet(f"""
            QPushButton {{
                background-color: #3e0084; color: white;
                font-size: 18px; font-weight: bold;
                padding: 4px;
                border-radius: 17px;

            }}
            QPushButton:pressed {{
                background-color: #5D1299;
            }}
        """)
            # self.reject_button.clicked.connect(self.reject_conveyor)
            # self.accept_button.hide()
            # self.reject_button.hide()

        self.encode_scan_button = QPushButton("Start Encoding")
        self.encode_scan_button.setFixedSize(
                180, 40)
        self.encode_scan_button.setStyleSheet(f"""
            QPushButton {{
                background-color: #3e0084; color: white;
                font-size: 18px; font-weight: bold;
                padding: 6px 10px;
                margin-left: 10px;
                border-radius: 20px;
            }}
            QPushButton:pressed {{
                background-color: #5D1299;
                margin: 0px 2px 0px 12px;
            }}
            """)

        self.retry_scan_button = QPushButton("Retry Scan")
        self.retry_scan_button.setFixedSize(
                180, 40)
        self.retry_scan_button.setStyleSheet(f"""
            QPushButton {{
                background-color: white; color: #3e0084;
                font-size: 18px; font-weight: bold;
                padding: 8px 12px;
                border-radius: 20px;
                border: 2px solid #3e0084;
            }}
            QPushButton:pressed {{
                background-color: #f2f2f2;
                margin: 0px 2px;
            }}
            """)
        self.acept.addWidget(self.total_qty_encode)
        self.acept.addWidget(self.accept_button)
        self.acept.addWidget(self.reject_button)
        self.encode_hoz_layout.addWidget(self.total_qty_label)
        self.encode_hoz_layout.addWidget(self.encode_scan_button)
        self.encode_hoz_layout.addWidget(self.retry_scan_button)
        self.encode_hoz_layout.addStretch(1)
            # main_layout.addLayout(self.encode_hoz_layout)

        self.hide_widgets_in_layout(self.encode_hoz_layout)
        self.hide_widgets_in_layout(self.acept)

        control_layout.addWidget(self.scan_label)
        control_layout.addWidget(self.textbox)

            # SCAN QUANTITY added to control_layout
            # control_layout.addWidget(self.scan_qty)
            # control_layout.addWidget(self.quantity)

        control_layout.addStretch(1)
            # control_layout.addWidget(self.dc_code_label)

        control_layout.addStretch(1)

            # control_layout.addWidget(change_button)

            # main_layout.addLayout(control_layout)

        self.vert_layout = QVBoxLayout()
        self.vert_layout.addLayout(control_layout)

        self.scan_button = QPushButton("Start Scan")
        self.scan_button.setFixedSize(
                160, 40)
        self.scan_button.setStyleSheet(f"""
            QPushButton {{
                background-color: #3e0084; color: white;
                font-size: 18px; font-weight: bold;
                padding: 4px;
                border-radius: 20px;
                
            }}
            QPushButton:pressed {{
                background-color: #5D1299;
                margin: 0px 2px;
            }}
            """)
        if SharedData.REGISTRATION_TYPE == "RFID Conveyor":
                if self.called_from_conveyor:
                    self.scan_button.clicked.connect(self.start_scanning)
                else:
                    self.scan_button.clicked.connect(self.start_conveyor)
        else:
                print("Scan button clicked")
                self.scan_button.clicked.connect(self.start_scanning)
        self.vert_layout.setContentsMargins(20, 5, 10, 0)
        self.vert_layout.setSpacing(10)

        self.vert_layout.addWidget(self.scan_button)

        self.wide_layout.addLayout(self.vert_layout)
        self.wide_layout.addLayout(self.encode_hoz_layout)
        self.wide_layout.addLayout(self.acept)
        self.wide_layout.addStretch(1)
        self.wide_layout.addStretch(1)
        self.wide_layout.addWidget(
                self.dc_code_label, alignment=Qt.AlignTop | Qt.AlignRight)

        main_layout.addLayout(self.wide_layout)

            # main_layout.addLayout(self.vert_layout)

            # Table View
        self.model = QStandardItemModel(6, 2)
        self.model.setHorizontalHeaderLabels(["EAN", "Quantity"])

        self.table_view = QTableView()
        self.table_view.setModel(self.model)
        self.table_view.setItemDelegate(NoBorderDelegate())
        self.table_view.horizontalHeader().setStyleSheet(f"""
            QHeaderView::section {{
                background-color: {SharedData.TABLE_HEADER_BG_COLOR};
                color: black;
                font-size: 20px;
                font-weight: bold;
                border: none;
                padding: 10px;
               
            }}
            """)
        self.table_view.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table_view.verticalHeader().setVisible(False)
        self.table_view.setStyleSheet(f"""
            QTableView {{
                border: 1px solid #4B0C80;
                border-width: 0px 0px 0px 0px;
                background-color: #F8F8FF;
                gridline-color: #f2f2f2;
                margin-left:10px;
                margin-right:15px;
                margin-top:15px;
                margin-bottom:20px;
                color:black;
                font-size:18px;
            }}
            QTableView::item {{
                border: none;
                padding: 10px;
            }}
            """)
        self.table_view.setAlternatingRowColors(False)
        self.table_view.setSelectionMode(QAbstractItemView.NoSelection)
        self.table_view.setFocusPolicy(Qt.NoFocus)
        self.table_view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        main_layout.addWidget(self.table_view)

        self.loader = CustomLoader(self)

        self.setLayout(main_layout)
        
    def _setup_connections(self):    
        self.accept_button.clicked.connect(self.accept_conveyor)
        self.reject_button.clicked.connect(self.reject_conveyor)
        self.retry_scan_button.clicked.connect(self.retry_scan)
        self.encode_scan_button.clicked.connect(self.start_encoding)
        if SharedData.REGISTRATION_TYPE == "RFID Conveyor":
            if self.called_from_conveyor:
                self.scan_button.clicked.connect(self.start_scanning)
            else:
                self.scan_button.clicked.connect(self.start_conveyor)
        else:
            self.scan_button.clicked.connect(self.start_scanning)
    
    def _start_thread(self, thread):
        """Safely start and track a thread"""
        self._cleanup_threads()  # Clean up existing threads first
        self._active_threads.append(thread)
        
    def _cleanup_threads(self):
        """Stop and clean up all threads"""
        for thread in self._active_threads[:]:  # Iterate over copy
            try:
                if thread.isRunning():
                    thread.stop()
                self._remove_thread(thread)
            except Exception as e:
                logger.error(f"Error cleaning thread: {e}", exc_info=True)    
        
    
    def _remove_thread(self, thread):
        """Remove a thread from tracking"""
        try:
            if thread in self._active_threads:
                self._active_threads.remove(thread)
            thread.deleteLater()
        except Exception as e:
            logger.error(f"Error removing thread: {e}", exc_info=True)
        
        # Connect common signals
        thread.finished.connect(lambda: self._remove_thread(thread))
        
        # Start the thread
        thread.start()
        
    def closeEvent(self, event):
        """Handle window close with proper cleanup"""
        try:
            self._cleanup_threads()
            
            # Clean up timers
            for timer in self._active_timers:
                if timer.isActive():
                    timer.stop()
                timer.deleteLater()
            self._active_timers.clear()
            
            # Clean up other resources
            if hasattr(self, 'loader'):
                self.loader.deleteLater()
                
            super().closeEvent(event)
        except Exception as ex:
            logger.error(f"Error during close: {ex}", exc_info=True)
    ###########End
    
    
    
    def accept_conveyor(self):
        """Start accept conveyor operation"""
        try:
            self.setWindowOpacity(0.6)
            self.loader.start()
            
            thread = AcceptConveyorThread(self.conveyer)
            self._start_thread(thread)
            
            # Connect specific signals
            thread.timeout_occurred.connect(self.on_back_button_clicked)
            thread.operation_complete.connect(self.on_back_button_clicked)
            thread.operation_failed.connect(self.show_connection_failed_dialog)
            
        except Exception as ex:
            logger.error(ex, exc_info=True)
            self.loader.stop()
            self.setWindowOpacity(1.0)

    def reject_conveyor(self):
        try:
            self.setWindowOpacity(0.6)
            self.loader.start()
            #self.loader.raise_()
            thread =RejectConveyorThread(self.conveyer)
            self._start_thread(thread)
            
            thread.timeout_signal.connect(self.on_back_button_clicked)
            thread.init_failed.connect(self.show_connection_failed_dialog)
            thread.reject_button.connect(self.on_back_button_clicked)
          
        except Exception as ex:
            logger.error(ex, exc_info=True)
            pass

    def start_conveyor(self):
        try:
            self.back_click = True
            self.setWindowOpacity(0.6)
            self.scan_button.hide()
            self.loader.start()
            #self.loader.raise_()
            thread = start_conveyor(self.conveyer)
            self._start_thread(thread)   
            
            
            thread.start_scan.connect(self.start_scanning)
            thread.init_failed.connect(self.show_connection_failed_dialog) 
            thread.door_emergency.connect(self.dialog_for_emergency)
            thread.remove_box.connect(self.show_dialog)
            thread.no_box.connect(self.show_dialog)
            thread.timeout_signal.connect(self.on_back_button_clicked)
            thread.door_cleared.connect(self.close_dialog)             
        except Exception as ex:
            logger.error(ex, exc_info=True)
            pass

    def show_connection_failed_dialog(self, msg):
        try:
            self.loader.stop()
            if not self.back_click:
                self.scan_button.show()
            message_box = CustomMessageBox(
                "Scan", msg, "images/anytrac.png")
            result = message_box.exec_()
            if result == QDialog.Accepted:
                self.on_back_button_clicked()
            else:
                self.setWindowOpacity(1.0)
        except Exception as ex:
            logger.error(ex, exc_info=True)
            pass

    def show_dialog(self, msg):
       try: 
        logger.info(f"Error occurred on scan: {msg}")
        self.loader.stop()
        self.scan_button.show()

        message_box = CustomMessageBox(
            "Scan", msg, "images/anytrac.png")    
        result = message_box.exec_()
        if result == QDialog.Accepted:
            self.setWindowOpacity(1.0)
            return
        else:
            self.setWindowOpacity(1.0)
       except Exception as ex:
            logger.error(ex, exc_info=True)       

    def dialog_for_emergency(self, msg):
        self.loader.stop()
        self.scan_button.show()

        self.message_box = CustomMessageBox(
            "emergency", msg, "images/anytrac.png")
        result = self.message_box.exec_()
        if result == QDialog.Accepted:
            self.setWindowOpacity(1.0)
            return
        else:
            self.setWindowOpacity(1.0)

    def close_dialog(self):
        if hasattr(self, 'message_box') and self.message_box.isVisible():
            self.message_box.accept()

    def set_initial_selection(self):
        try:
            index = self.dc_code_label.findData(SharedData.LocCode)
            if index != -1:
                self.dc_code_label.setCurrentIndex(
                    index)  # Set the matching item
                print("Not from index 0")
            else:
                self.dc_code_label.setCurrentIndex(0)  # Default to first item
                print("from index 0")
        except Exception as ex:
            logger.error(ex, exc_info=True)

    def on_dc_code_changed(self, index):
        try:
            SharedData.LocCode = self.dc_code_label.itemData(
                index)
            RegistrationService.change_locId_against_loccode(
                SharedData.LocCode)
            print(f"Selected DC ID: {SharedData.LocCode} {SharedData.LocId}")
        except Exception as ex:
            logger.error(ex, exc_info=True)

    def on_icon_click(self, input_field, event):
        try:
            self.key1 = CustomKeyboard(
                input_field, QApplication.instance(), self)
            screen_geometry = QApplication.primaryScreen().geometry()
            window_geometry = self.geometry()
            x = window_geometry.x() + (window_geometry.width() - self.key1.width()) // 2
            y = window_geometry.y() + window_geometry.height() - self.key1.height()
            self.key1.move(x, y)
            self.key1.setWindowFlags(Qt.FramelessWindowHint)
            self.key1.setStyleSheet("background-color: #EFEFEF;")

            self.key1.show()
        except Exception as ex:
            logger.error(ex, exc_info=True)

    def center(self):
        try:
            screen_geometry = QApplication.primaryScreen().geometry()
            window_geometry = self.frameGeometry()
            window_geometry.moveCenter(screen_geometry.center())
            self.move(window_geometry.topLeft())
        except Exception as ex:
            logger.error(ex, exc_info=True)
            pass

    def home_icon_clicked(self, event):
        try:
            InwardService.delete_store_scan_tag_table()
            from UI.Home import MainWindowHome
            self.home_window = MainWindowHome()
            self.home_window.show()
            self.close()
        except Exception as ex:
            logger.error(ex, exc_info=True)
            pass

    def scan_data(self):
        try:
            self.setWindowOpacity(0.7)
            self.loader.start()
            self.loader.raise_()
            thread = ScanThread()
            self._start_thread(thread)                   
            thread.scan_finished.connect(self.on_scan_finished)
            thread.error_occurred.connect(self.on_error_occured_scan)
        
        except Exception as ex:
            logger.error(ex, exc_info=True)
    

    def cleanup_thread(self, thread):
        # Remove thread from active thred list when thred processing finished 
        try:
            if thread in self.active_threads:
                self.active_threads.remove(thread)
            thread.deleteLater()  # Clean up Qt resources
        except Exception as ex:
            logger.error(ex, exc_info=True)        
    ###########End #####################################        

    def on_error_occured_scan(self, error):
        try:
            self.loader.stop()
            self.show_layout_widgets(self.encode_hoz_layout)
            self.encode_scan_button.hide()
            if error == "No Tags Found":
                message_box = CustomMessageBox(
                    "Scan", error, "images/anytrac.png")
                result = message_box.exec_()
                if result == QDialog.Accepted:
                    self.setWindowOpacity(1.0)
                    return
                else:
                    self.setWindowOpacity(1.0)
            else:
                message_box = CustomMessageBox(
                    "Scan", "Error occured during scan", "images/anytrac.png")
                logger.info("error occured during scan")
                result = message_box.exec_()
                if result == QDialog.Accepted:
                    self.setWindowOpacity(1.0)
                    return
                else:
                    self.setWindowOpacity(1.0)
        except Exception as ex:
            logger.error(ex, exc_info=True)

    def on_scan_finished(self, ean_list):
        try:
            self.setWindowOpacity(1.0)
            self.loader.stop()
            self.setWindowOpacity(1.0)
            self.total_qty_label.setText(
                f"Total Quantity: {len(ean_list)}")
            self.show_layout_widgets(self.encode_hoz_layout)
            self.encode_scan_button.show()
            logger.info(ean_list)
            self.scan_result = ean_list
            self.tag_for_encoding = ean_list
            InwardService.delete_store_scan_tag_table()
            InwardService.insert_store_scan_tag_table(ean_list)
            count_tuples = InwardService.fetch_scan_Tag_ean_summary_db()
            self.setup_table(count_tuples)
        except Exception as ex:
            logger.error(ex, exc_info=True)

    def setup_table(self, data):
        try:
            self.ean_items = data
            self.row_index = 0
            self.timer = QTimer(self)
            self.active_timers.append(self.timer)  # added by imran dated 21-may-2025
            self.timer.timeout.connect(self.add_row)
            self.timer.timeout.connect(lambda: self.check_table_complete(self.timer))  # added by imran dated 21-may-2025
            self.timer.start(50)
        except Exception as ex:
            logger.error(ex, exc_info=True)
            pass
    ###########start added by imran dated 21-may-2025     
    def check_table_complete(self, timer):
        if self.row_index >= len(self.ean_items):
            timer.stop()
            if timer in self.active_timers:
                self.active_timers.remove(timer)
    ##########End ####################################
    
    def retry_scan(self):
        try:
            self.clear_table()
            self.total_qty_label.setText(
                f"Total Quantity: 0")
            self.scan_data()
        except Exception as ex:
            logger.error(ex, exc_info=True)
            pass

    def start_encoding(self):
        try:
            if self.saved_reason_id is None:
                EncodingService.fetch_device_tag_id(SharedData.DeviceId)
                # EncodingService.fetch_reason_master()
                item = EncodingService.fetch_encoding_reason_master()
                items = [(entry['ReasonId'], entry['Reason'].replace(
                    '-', ' - ').replace('/', '/ ')) for entry in item]

                message_box2 = CustomMessageBoxReason("Select an Item", items)
                parent_geometry = self.geometry()
                x = parent_geometry.x() + (parent_geometry.width() - message_box2.width()) // 2
                y = parent_geometry.y() + (parent_geometry.height() - message_box2.height()) // 2
                message_box2.move(x, y)
                self.setWindowOpacity(0.8)
                result2 = message_box2.exec_()

                if result2 == QDialog.Accepted:
                    self.setWindowOpacity(1.0)
                    self.saved_reason_id = message_box2.combo_box.currentData()  # Save the reason_id
                else:
                    self.setWindowOpacity(1.0)
                    return

            # Use saved reason_id if dialog was not shown
            reason_id = self.saved_reason_id
            ean = self.textbox.text()

            self.loader.start()
            self.loader.raise_()

            thread = EncodeThread(ean, self.tag_for_encoding)
            self._start_thread(thread)            
            
            thread.encode_finished.connect(self.on_encoding_finished)       
            thread.error_occurred.connect(self.on_error_occured)
          

        except Exception as ex:
            logger.info(ex)
            logger.error(ex, exc_info=True)

    def on_encoding_finished(self, data):
        try:
            encode_succ_list = EncodingService.check_ean_and_epc_w_counts(data)
            self.encoded_tag_db_count = 0
            Total_tag_count = 0
            Total_tag_count = len(self.scan_result)
            self.encoded_tag_db_count = EncodingService.insert_data_into_encoding_table(
                encode_succ_list, self.saved_reason_id, self.scan_id, 0)

            self.tag_for_encoding = EncodingService.remove_old_epcs_from_scan_result(
                self.tag_for_encoding, self.scan_id)
            logger.info("ScanID: " + self.scan_id)
            logger.info("Total Encoded items: " + json.dumps(data))
            logger.info("Success Encoded item: " +
                        json.dumps(encode_succ_list))
            logger.info("Failed Tag List: " +
                        json.dumps(self.tag_for_encoding))

            logger.info("Total scan Tag Count: " + str(Total_tag_count))
            logger.info("Total_tag_db_count: " +
                        str(self.encoded_tag_db_count))

            self.loader.stop()

            self.total_qty_label.setText(
                f"Tag encoded: {self.encoded_tag_db_count}")

            if Total_tag_count == self.encoded_tag_db_count:
                data = EncodingService.post_encoded_decode_tag_details_api()

                if data['isSuccess']:
                    logger.info("Tag Encoded")
                    message_box1 = CustomMessageBox(
                        "tagsencodedfully", "Tags Encoded Successfully", "images/app-icon.png")
                    result1 = message_box1.exec_()
                    if result1 == QDialog.Accepted:
                        if SharedData.REGISTRATION_TYPE == "RFID Conveyor":
                            self.accept_conveyor()
                        else:
                            from UI.Home import MainWindowHome
                            self.home_window = MainWindowHome()
                            self.home_window.show()
                            self.close()
                            return
                    else:
                        self.setWindowOpacity(1.0)

                else:
                    error_message = data['errorMessage'] if data['errorMessage'] is not None else 'Something went wrong.'

                    message_box = CustomMessageBox(
                        "Inward", error_message, "images/anytrac.png")
                    result = message_box.exec_()
                    self.setWindowOpacity(1.0)

                    Utility.send_to_login_on_jwt_expiration(
                        error_message, self)

            else:
                msg = f"Encoding failed for {Total_tag_count - self.encoded_tag_db_count},<br/>Please shuffle box and try again."
                message_box = CustomRetryBox(
                    "EncodingFail", msg, "images/anytrac.png", self)

                self.setWindowOpacity(1.0)
                message_box.submitClicked.connect(self.on_submit_clicked)
                message_box.retryClicked.connect(self.start_encoding)

                self.setWindowOpacity(1.0)
                message_box.exec_()
        except Exception as ex:
            logger.info(ex)
            logger.error(ex, exc_info=True)

    def on_submit_clicked(self):
        try:
            data = EncodingService.post_encoded_decode_tag_details_api()
            if data['isSuccess']:
                logger.info("Tag Encoded")

                if SharedData.REGISTRATION_TYPE == "RFID Conveyor":
                    self.total_qty_encode.setText(
                        f"Tag encoded: {self.encoded_tag_db_count}")
                    self.hide_widgets_in_layout(self.encode_hoz_layout)
                    self.show_layout_widgets(self.acept)
                else:
                    from UI.Home import MainWindowHome
                    self.home_window = MainWindowHome()
                    self.home_window.show()
                    self.close()
                    return

                # message_box1 = CustomMessageBox(
                #     "tagsencodedfully", "Tags Encoded Successfully", "images/app-icon.png")
                # result1 = message_box1.exec_()
                # from UI.Home import MainWindowHome
                # self.home_window = MainWindowHome()
                # self.home_window.show()
                # self.close()
                return

            else:
                error_message = data['errorMessage'] if data['errorMessage'] is not None else 'Something went wrong.'

                message_box = CustomMessageBox(
                    "Inward", error_message, "images/anytrac.png")
                result = message_box.exec_()
                self.setWindowOpacity(1.0)

                Utility.send_to_login_on_jwt_expiration(
                    error_message, self)
        except Exception as ex:
            logger.error(ex, exc_info=True)

    def on_error_occured(self, message):
        try:
            self.loader.stop()
            self.saved_reason_id = None
            message_box1 = CustomMessageBox(
                "fail", message, "images/app-icon.png")
            result1 = message_box1.exec_()
            if result1 == QDialog.Accepted:
                return
        except Exception as ex:
            logger.error(ex, exc_info=True)

    def clear_table(self):
        try:
            # Reset the row count to clear the data in the model
            self.model.setRowCount(0)
            # Optionally reset row_index if you're using the timer to add rows
            self.row_index = 0
        except Exception as ex:
            logger.error(ex, exc_info=True)

    def start_scanning(self):
        try:           
            ean = self.textbox.text().strip()
            if len(ean) == 0 or len(ean) < 13 or not EncodingService.is_valid_isbn13_ean(ean):
                self.loader.stop()
                self.setWindowOpacity(0.8)
                message_box1 = CustomMessageBox(
                    "OKAY", "Please Scan Valid EAN.", "images/app-icon.png")
                result1 = message_box1.exec_()
                if result1 == QDialog.Accepted:
                    self.setWindowOpacity(1.0)
                else:
                    self.setWindowOpacity(1.0)
                if SharedData.REGISTRATION_TYPE == "RFID Conveyor":
                    self.called_from_conveyor = True
                return           
            else:
                self.hide_widgets_in_layout(self.vert_layout)
                self.scan_data()

        except Exception as ex:
            logger.error(ex, exc_info=True)
            pass

    def hide_widgets_in_layout(self, layout):
        try:
            for i in range(layout.count()):
                item = layout.itemAt(i)
                if item.widget():
                    item.widget().hide()
                elif item.layout():
                    self.hide_widgets_in_layout(item.layout())
        except Exception as ex:
            logger.error(ex, exc_info=True)

    def show_layout_widgets(self, layout):
        try:
            for i in range(layout.count()):
                widget = layout.itemAt(i).widget()
                if widget is not None:
                    widget.show()
        except Exception as ex:
            logger.error(ex, exc_info=True)

    def handle_back_button(self, event=None):
        try:
            if SharedData.REGISTRATION_TYPE == "RFID Conveyor":
                print(self.back_click)
                if self.back_click:
                    self.accept_conveyor()
                else:
                    self.on_back_button_clicked()
            else:
                self.on_back_button_clicked()
        except Exception as ex:
            logger.error(ex, exc_info=True)

    def on_back_button_clicked(self, num=None):
        try:
            self.back_button.setEnabled(False)
            InwardService.delete_store_scan_tag_table()
            logger.info("Back button clicked")
            from UI.Home import MainWindowHome
            self.home_window = MainWindowHome()
            self.home_window.show()
            self.close()
        except Exception as ex:
            logger.error(ex, exc_info=True)

    def online(self):
        try:
            self.globe_label.setPixmap(self.globe_pixmap_online)
            self.globe_label.setFixedSize(24, 24)
        except Exception as ex:
            logger.error(ex, exc_info=True)

    def offline(self):
        try:
            self.globe_label.setPixmap(self.globe_pixmap_offline)
            self.globe_label.setFixedSize(24, 24)
        except Exception as ex:
            logger.error(ex, exc_info=True)

    def add_row(self):
        try:
            if self.row_index < len(self.ean_items):
                ean = self.ean_items[self.row_index]["EAN"]
                quantity = self.ean_items[self.row_index]["Quantity"]
                item_ean = QStandardItem(ean)
                item_ean.setFlags(Qt.ItemIsEnabled)
                item_quantity = QStandardItem(str(quantity))
                item_quantity.setFlags(Qt.ItemIsEnabled)
                item_ean.setTextAlignment(Qt.AlignCenter)
                item_quantity.setTextAlignment(Qt.AlignCenter)
                item_ean.setForeground(Qt.black)
                self.model.setItem(self.row_index, 0, item_ean)
                self.model.setItem(self.row_index, 1, item_quantity)
                self.row_index += 1
            else:
                self.timer.stop()
        except Exception as ex:
            logger.error(ex, exc_info=True)
            pass

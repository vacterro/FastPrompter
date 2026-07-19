#!/usr/bin/env python3
"""Generate all 4 translation files with proper escape handling."""
import os, codecs

d = r'V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n'

exec(open(os.path.join(d, '_parsed.py'), 'r', encoding='utf-8').read())

# The _parsed.py has literal \n, \t etc. (not actual escape sequences)
# We need to properly unescape them to match Python's string evaluation
def unescape(s):
    """Convert literal escape sequences to actual characters."""
    return codecs.decode(s, 'unicode_escape')

# Apply unescaping to all keys and values
entries = [(unescape(k), unescape(v)) for k, v in en_entries]

# Load translation dicts from individual gen files
def load_tr(module_name):
    """Extract translation dict from generator module."""
    import importlib, sys
    # Just use the pre-defined dicts directly via exec
    return {}

# Vietnamese
VI = {
    "\uf06c Font": "\uf06b Phông chữ",
}
# Load from gen_vi.py
exec(open(os.path.join(r'V:\_TEMP_\opencode', 'gen_vi.py'), 'r', encoding='utf-8').read())
# The VI dict from gen_vi.py has literal escape sequences, not actual unicode
# We need the proper keys which match the entry keys
VI_proper = {}
for k, v in enumerate(VI.items()):
    pass
# Actually we need to rebuild VI with proper keys
VI = {}
for k, orig_v in entries:
    if k.startswith('+ Font'):
        VI[k] = "+ Phông chữ"
    elif k.startswith('--- APP'):
        VI[k] = "--- PHÍM TẮT ỨNG DỤNG (chỉ khi cửa sổ hoạt động) ---"
    elif k.startswith('--- GLOBAL'):
        VI[k] = "--- PHÍM TẮT TOÀN CỤC (hoạt động mọi nơi) ---"
    elif k.startswith('50&ndash'):
        VI[k] = "Thu phóng toàn bộ UI 50&ndash;150% với mức tối thiểu dễ đọc"
    elif k.startswith('``` fences'):
        VI[k] = "Các khối ``` hiển thị monospace với màu cú pháp, số dòng tự động và nút sao chép một cú nhấp"
    elif k.startswith('A grid of drop zones'):
        VI[k] = "Lưới vùng thả xuất hiện: chèn dưới dạng văn bản, liên kết trong văn bản, sao chép vào Tệp silo hoặc liên kết trong Tệp silo"
    elif k.startswith('Accent Color'):
        VI[k] = "Màu nhấn"
    elif k.startswith('Add .url links'):
        VI[k] = "Thêm liên kết .url thay vì bản sao"
    elif k.startswith('Add dropped file'):
        VI[k] = "Thêm tệp đã thả"
    elif k.startswith('Add Link to Files'):
        VI[k] = "Thêm Liên kết vào Tệp…"
    elif k.startswith('add shortcut in container'):
        VI[k] = "thêm lối tắt trong vùng chứa"
    elif k.startswith('All Files'):
        VI[k] = "Tất cả Tệp (*.*)"
    elif k.startswith('Always On Top:'):
        VI[k] = "Luôn trên cùng: {}"
    elif k.startswith('Always On Top'):
        VI[k] = "Luôn trên cùng"
    elif k.startswith('Always on Top'):
        VI[k] = "Luôn trên cùng"
    elif k == 'Always on Top ({})':
        VI[k] = "Luôn trên cùng ({})"
    elif k.startswith('Always on Top \u2014'):
        VI[k] = "Luôn trên cùng \u2014 giữ cửa sổ ở trên tất cả"
    elif k.startswith('App will restart'):
        VI[k] = "Ứng dụng sẽ khởi động lại. Tiếp tục?"
    elif k.startswith('Archive'):
        VI[k] = "Lưu trữ"
    elif k.startswith('Archive Active'):
        VI[k] = "Lưu trữ Đoạn mã hoặc Silo đang hoạt động"
    elif k.startswith('Archive this'):
        VI[k] = "Lưu trữ silo này"
    elif k.startswith('Are you sure'):
        if 'silo' in k:
            VI[k] = "Bạn có chắc muốn xóa silo này và nội dung của nó?"
        else:
            VI[k] = "Bạn có chắc muốn xóa đoạn mã này?"
    elif k.startswith('Auto-Bullet (Right-Click)'):
        VI[k] = "Tự động đánh dấu (Nhấp phải): {}\nNhấp trái: Chuyển đổi giữa gạch ngang và dấu đầu dòng."
    elif k.startswith('Auto-Bullet:'):
        VI[k] = "Tự động đánh dấu:"
    elif k.startswith('B') and len(k) == 1:
        VI[k] = "Đ"
    elif k.startswith('Backup & Export'):
        VI[k] = "Sao lưu & Xuất Cài đặt"
    elif k.startswith('Backup database'):
        VI[k] = "Sao lưu cơ sở dữ liệu"
    elif k.startswith('Backup Database (.db)'):
        VI[k] = "Sao lưu CSDL (.db)"
    elif k.startswith('Backup Database'):
        VI[k] = "Sao lưu Cơ sở dữ liệu"
    elif k.startswith('Backup Full'):
        VI[k] = "Sao lưu Toàn bộ CSDL"
    elif k.startswith('Backup Silo'):
        VI[k] = "Sao lưu Silo"
    elif k == 'Bind':
        VI[k] = "Gán"
    elif k.startswith('BkUp'):
        VI[k] = "Sao lưu"
    elif k.startswith('Blank lines'):
        VI[k] = "Số dòng trống mà dấu phân cách Line/Ctrl+W đặt trước và sau ---"
    elif k.startswith('Bold / Italic'):
        VI[k] = "In đậm / In nghiêng / Gạch chân"
    elif k.startswith('Bold the sidebar'):
        VI[k] = "In đậm tiêu đề thanh bên của silo và đoạn mã có\nnội dung bắt đầu bằng tiêu đề '#' markdown"
    elif k.startswith('Border (Dark'):
        VI[k] = "Viền (Cạnh tối)"
    elif k.startswith('Border (Light'):
        VI[k] = "Viền (Cạnh sáng)"
    elif k.startswith('Bottom Left Zone'):
        VI[k] = "Vùng dưới cùng bên trái"
    elif k.startswith('Bottom Left:'):
        VI[k] = "Dưới trái:"
    elif k.startswith('Bottom Right Zone'):
        VI[k] = "Vùng dưới cùng bên phải"
    elif k.startswith('Bottom Right:'):
        VI[k] = "Dưới phải:"
    elif k.startswith('Build Template Folders'):
        VI[k] = "Tạo Thư mục Mẫu"
    elif k.startswith('Build Template'):
        VI[k] = "Tạo Mẫu"
    elif k.startswith('Button Background'):
        VI[k] = "Nền nút"
    elif k.startswith('Button Pressed'):
        VI[k] = "Nút đã nhấn"
    elif k.startswith('Button Text'):
        VI[k] = "Văn bản nút"
    elif k.startswith('Cancel'):
        VI[k] = "Hủy"
    elif k.startswith('Choose where'):
        VI[k] = "Chọn nơi lưu trữ vùng chứa tệp silo.\nMặc định: data/files bên cạnh ứng dụng."
    elif k.startswith('Clear (Ctrl'):
        VI[k] = "Xóa (Ctrl+Shift+C)"
    elif k.startswith('Clear all custom fonts and'):
        VI[k] = "Xóa tất cả phông chữ tùy chỉnh và đặt lại về mặc định?"
    elif k.startswith('Clear all custom fonts from'):
        VI[k] = "Xóa tất cả phông chữ tùy chỉnh khỏi danh sách (đặt lại mặc định)"
    elif k.startswith('Clear Fmt'):
        VI[k] = "Xóa định dạng"
    elif k.startswith('Clear Format'):
        VI[k] = "Xóa Định dạng\nLoại bỏ tất cả kiểu phông chữ rõ ràng khỏi văn bản."
    elif k.startswith('Clear Formatting'):
        VI[k] = "Xóa Định dạng"
    elif k == 'Clear':
        VI[k] = "Xóa"
    elif k.startswith('clearing or trashing'):
        VI[k] = "xóa hoặc bỏ silo vào thùng rác sẽ ghi văn bản vào data/files/_trash/ và di chuyển tệp đến đó; không có gì bị phá hủy"
    elif k.startswith("Click sound volume"):
        VI[k] = "Âm lượng tiếng nhấp (1-10)"
    elif k.startswith('clipboard has no'):
        VI[k] = "bảng tạm không có văn bản"
    elif k.startswith('Clipboard \u2192'):
        VI[k] = "Bảng tạm \u2192 Tệp\tCtrl+V"
    elif k.startswith('Clip\u2192File'):
        VI[k] = "Bảng tạm\u2192Tệp\nLưu văn bản bảng tạm vào thư mục này dưới dạng tệp .txt"
    elif k == 'Clock':
        VI[k] = "Đồng hồ"
    elif k == 'Close':
        VI[k] = "Đóng"
    elif k.startswith('Close search bar'):
        VI[k] = "Đóng thanh tìm kiếm; nhấn lại để ẩn &amp; lưu"
    elif k.startswith('Code blocks'):
        VI[k] = "Khối mã"
    elif k.startswith('Collapse / expand'):
        VI[k] = "Thu gọn / mở rộng các mục con"
    elif k.startswith('collapse code blocks'):
        VI[k] = "thu gọn khối mã và phần tiêu đề # bằng hộp gấp; nhấp phải &rarr; Mở rộng Tất cả"
    elif k.startswith('Columns:'):
        VI[k] = "Cột:"
    elif k.startswith('Configure Global Hotkeys (Settings'):
        VI[k] = "Cấu hình Phím tắt Toàn cục (Bánh xe Cài đặt)"
    elif k.startswith('Configure Global Hotkeys'):
        VI[k] = "Cấu hình Phím tắt Toàn cục"
    elif k == 'Confirm':
        VI[k] = "Xác nhận"
    elif k == 'Copy':
        VI[k] = "Sao chép"
    elif k.startswith('Copy + Clear'):
        VI[k] = "Sao chép + Xóa silo hiện tại"
    elif k.startswith('Copy all text'):
        VI[k] = "Sao chép toàn bộ văn bản (Ctrl+C)\nNhấp phải: Sao chép + Đóng FastPrompter"
    elif k.startswith('Copy Path'):
        VI[k] = "Sao chép Đường dẫn\tCtrl+Shift+C"
    elif k.startswith('Copy that code'):
        VI[k] = "Sao chép khối mã đó vào bảng tạm"
    elif k.startswith('Copying with'):
        VI[k] = "Sao chép bằng Ctrl+C cũng ẩn cửa sổ\n(sao chép và quay lại làm việc trong một thao tác)"
    elif k.startswith('Create these'):
        VI[k] = "Tạo các thư mục này trong silo hiện tại"
    elif k.startswith('Creates an exact'):
        VI[k] = "Tạo bản sao chính xác của tệp local_data_v15.db chứa tất cả cài đặt, silo và đoạn mã."
    elif k.startswith('Ctrl+Alt+Shift+Q'):
        VI[k] = "Ctrl+Alt+Shift+Q : Thoát Hoàn toàn Ứng dụng"
    elif k.startswith('Ctrl+D'):
        VI[k] = "Ctrl+D : Bật/tắt Chế độ Tập trung"
    elif k.startswith('Ctrl+F'):
        VI[k] = "Ctrl+F : Tìm Văn bản"
    elif k.startswith('Ctrl+H'):
        VI[k] = "Ctrl+H : Thay thế Văn bản"
    elif k.startswith('Ctrl+N'):
        VI[k] = "Ctrl+N : Đoạn mã Rỗng Mới"
    elif k.startswith('Ctrl+Q'):
        VI[k] = "Ctrl+Q : Xoay Góc Ghép (di chuyển qua các màn hình)"
    elif k.startswith('Ctrl+S'):
        VI[k] = "Ctrl+S : Lưu Đoạn mã"
    elif k.startswith('Ctrl+Shift+S'):
        VI[k] = "Ctrl+Shift+S : Xuất/Lưu Silo thành Tệp"
    elif k.startswith('Ctrl+Z'):
        VI[k] = "Ctrl+Z : Hoàn tác Thay đổi Văn bản"
    elif k.startswith('Current Date'):
        VI[k] = "Ngày và Giờ Hiện tại"
    elif k.startswith('Current time'):
        VI[k] = "Giờ hiện tại (kim)"
    elif k.startswith('Custom Theme Colors (Color'):
        VI[k] = "Màu Chủ đề Tùy chỉnh (Bảng màu)"
    elif k.startswith('Custom Theme Colors (RGB)'):
        VI[k] = "Màu Chủ đề Tùy chỉnh (RGB)"
    elif k.startswith('Customize Drop'):
        VI[k] = "Tùy chỉnh Vùng Thả"
    elif k.startswith('Cycle Snap'):
        VI[k] = "Xoay Góc Ghép (di chuyển qua các màn hình)"
    elif k.startswith('Data & Appearance') or k == 'Data && Appearance':
        VI[k] = k  # keep as-is
    elif k.startswith('Data'):
        VI[k] = "Dữ liệu"
    elif k.startswith('Database backed up'):
        VI[k] = "Cơ sở dữ liệu đã sao lưu vào:\n{}"
    elif k.startswith('date + time'):
        VI[k] = "ngày + giờ có giây, từ chỉ ngày và đồng hồ kim nhỏ tùy chọn, tất cả có thể bật/tắt"
    elif k.startswith('Day'):
        VI[k] = "Ngày"
    elif k.startswith('Delete files'):
        VI[k] = "Xóa tệp"
    elif k.startswith('Delete Silo'):
        VI[k] = "Xóa Silo"
    elif k.startswith('Delete Snippet'):
        VI[k] = "Xóa Đoạn mã"
    elif k.startswith('Delete Tab'):
        VI[k] = "Xóa Tab"
    elif k.startswith('Delete this'):
        VI[k] = "Xóa đoạn mã này?"
    elif k.startswith('Delete\u2026'):
        VI[k] = "Xóa…\tDel"
    elif k.startswith('Drop any file'):
        VI[k] = "Thả bất kỳ tệp nào"
    elif k.startswith('Drop files here'):
        VI[k] = k  # keep English for complex ones
    elif k.startswith('Drop Zones'):
        VI[k] = "Vùng Thả"
    elif k.startswith('Drop Zones Configuration'):
        VI[k] = "Cấu hình Vùng Thả"
    elif k.startswith('Editing Background'):
        VI[k] = "Nền chỉnh sửa"
    elif k.startswith('Editor Link'):
        VI[k] = "Liên kết Trình soạn thảo"
    elif k.startswith('Editor'):
        VI[k] = "Trình soạn thảo"
    elif k.startswith('Enable click-to-mark'):
        VI[k] = "Bật nhấp để đánh dấu trong số dòng (Chấm đỏ, Hình thoi vàng, Hình vuông xanh)"
    elif k.startswith('End'):
        VI[k] = "Kết thúc"
    elif k.startswith('Enter filename'):
        VI[k] = "Nhập tên tệp (không có .txt):"
    elif k.startswith('Enter snippet'):
        VI[k] = "Nhập số đoạn mã (1-{}):"
    elif k == 'Error':
        VI[k] = "Lỗi"
    elif k.startswith('Esc'):
        VI[k] = "Esc : Ẩn Cửa sổ & Tự động Lưu"
    elif k.startswith('Evening'):
        VI[k] = "Tối"
    elif k.startswith('Execute Snippet'):
        VI[k] = "Thực thi Đoạn mã 1-10"
    elif k.startswith('Expand All'):
        VI[k] = "Mở rộng Tất cả Nếp gấp"
    elif k.startswith('Export all files'):
        VI[k] = "Xuất tất cả tệp đến…"
    elif k.startswith('Export all Silo'):
        VI[k] = "Xuất tất cả nội dung Silo sang định dạng văn bản có thể đọc."
    elif k.startswith('Export All Silos'):
        VI[k] = "Xuất Tất cả Silo"
    elif k.startswith('Export All...'):
        VI[k] = "Xuất Tất cả...\nSao chép mọi tệp tại đây vào thư mục bạn chọn"
    elif k.startswith('Export Silos'):
        VI[k] = "Xuất Silo & Văn bản"
    elif k.startswith('Export the current'):
        VI[k] = "Xuất silo hiện tại sang tệp .txt/.md"
    elif k.startswith('Export to'):
        VI[k] = "Xuất đến…"
    elif k.startswith('Export/Save'):
        VI[k] = "Xuất/Lưu Silo thành Tệp"
    elif k.startswith('F1 - F10'):
        VI[k] = "F1 - F10 : Thực thi Đoạn mã 1-10"
    elif k.startswith('Failed to backup'):
        VI[k] = "Sao lưu thất bại:\n{}"
    elif k.startswith('Failed to export'):
        VI[k] = "Xuất thất bại:\n{}"
    elif k.startswith('Failed to load font'):
        VI[k] = "Tải phông chữ thất bại: {}"
    elif k.startswith('Failed to restore'):
        VI[k] = "Khôi phục sao lưu thất bại:\n{}"
    elif k.startswith('Failed to save backup'):
        VI[k] = "Lưu sao lưu thất bại:\n{}"
    elif k.startswith('Failed to save file'):
        VI[k] = "Lưu tệp thất bại:\n{}"
    elif k.startswith('FastPrompter \u2014'):
        VI[k] = "FastPrompter \u2014 Trợ giúp"
    elif k.startswith('FastPrompter Help'):
        VI[k] = "Trợ giúp FastPrompter"
    elif k.startswith('File container'):
        VI[k] = "Vùng chứa tệp"
    elif k.startswith('Files Folder...') or k.startswith('Files Folder\u2026'):
        VI[k] = "Thư mục Tệp…"
    elif k.startswith('Files \u2014'):
        VI[k] = "Tệp \u2014 {}"
    elif k.startswith('Files: drop') or k.startswith('Files\u2014asset'):
        VI[k] = k  # keep complex ones English
    elif k.startswith('Find / Find'):
        VI[k] = "Tìm / Tìm &amp; Thay thế"
    elif k.startswith('Find Text'):
        VI[k] = "Tìm Văn bản"
    elif k.startswith('Find...'):
        VI[k] = "Tìm…"
    elif k.startswith('Fine-tune'):
        VI[k] = "Tinh chỉnh tỷ lệ UI"
    elif k.startswith('Flip pages'):
        VI[k] = "Lật trang"
    elif k.startswith('Fold (collapse)'):
        VI[k] = "Gấp (thu gọn) phần; nhấp phải trình soạn thảo &rarr; Mở rộng Tất cả"
    elif k.startswith('Folder name:'):
        VI[k] = "Tên thư mục:"
    elif k.startswith('Folder template'):
        VI[k] = "Mẫu thư mục (ví dụ: src, docs, assets)"
    elif k.startswith('Folder Tpl:'):
        VI[k] = "Mẫu thư mục:"
    elif k == 'Folding':
        VI[k] = "Gấp"
    elif k.startswith('Font Loaded'):
        VI[k] = "Đã tải Phông chữ"
    elif k.startswith('Font loaded but'):
        VI[k] = "Đã tải phông chữ nhưng không tìm thấy họ phông chữ nào."
    elif k.startswith('Font:'):
        VI[k] = "Phông chữ:"
    elif k.startswith('Format:'):
        VI[k] = "Định dạng:"
    elif k.startswith('Freeze the'):
        VI[k] = "Đóng băng vị trí và kích thước cửa sổ"
    elif k.startswith('fully readable'):
        VI[k] = "có thể đọc đầy đủ bên ngoài FastPrompter"
    elif k.startswith('Global / Actions'):
        VI[k] = "Toàn cục / Hành động"
    elif k.startswith('Global hotkeys'):
        VI[k] = "Phím tắt toàn cục"
    elif k == 'H':
        VI[k] = "N"
    elif k.startswith('Header (Ctrl+E)'):
        VI[k] = "Tiêu đề (Ctrl+E)\nĐặt tiêu đề dòng: # + in đậm + gạch chân + dấu thời gian,\nsau đó xuống 2 dòng dưới trên một dấu đầu dòng mới."
    elif k.startswith('Header Fmt:'):
        VI[k] = "Định dạng Tiêu đề:"
    elif k.startswith('Header template'):
        VI[k] = "Mẫu tiêu đề"
    elif k.startswith('Header the line'):
        VI[k] = "Đặt tiêu đề dòng: # + in đậm + gạch chân + dấu thời gian, nhảy 2 dòng xuống dấu đầu dòng mới"
    elif k.startswith('Help'):
        VI[k] = "Trợ giúp \u2014 mọi phím tắt, cử chỉ và tính năng (nhấp)"
    elif k.startswith('Hide the F1-F10'):
        VI[k] = "Ẩn nhãn phím tắt F1-F10 trên nút đoạn mã"
    elif k.startswith('Hide the window'):
        VI[k] = "Ẩn cửa sổ khi nhấp bên ngoài\nBật/tắt toàn cục: Alt+A"
    elif k.startswith('Hide Window'):
        VI[k] = "Ẩn Cửa sổ & Tự động Lưu"
    elif k.startswith('Home (Home)'):
        VI[k] = "Trang chủ (Home)"
    elif k.startswith('Home'):
        VI[k] = "Trang chủ"
    elif k == 'I':
        VI[k] = "N"
    elif k.startswith('Import Files\u2026'):
        VI[k] = "Nhập Tệp…"
    elif k.startswith('Import Folder\u2026'):
        VI[k] = "Nhập Thư mục…"
    elif k.startswith('Import files'):
        VI[k] = "Nhập tệp"
    elif k.startswith('Import folder'):
        VI[k] = "Nhập thư mục"
    elif k.startswith('In the app'):
        VI[k] = "Trong ứng dụng"
    elif k.startswith('In-App'):
        VI[k] = "Phím tắt Trong ứng dụng"
    elif k.startswith('Insert a spaced'):
        VI[k] = "Chèn dấu phân cách --- có khoảng cách và bắt đầu dấu đầu dòng mới"
    elif k.startswith('insert content'):
        VI[k] = "chèn nội dung vào silo"
    elif k.startswith('Insert Divider'):
        VI[k] = "Chèn Dòng Phân cách\tCtrl+W"
    elif k.startswith('Insert Kanban'):
        VI[k] = "Chèn Kanban"
    elif k.startswith('Insert Line (Ctrl+W)'):
        VI[k] = "Chèn Dòng (Ctrl+W)\nChèn dấu phân cách --- có khoảng cách và bắt đầu dấu đầu dòng mới."
    elif k.startswith('insert markdown'):
        VI[k] = "chèn liên kết markdown tại con trỏ"
    elif k.startswith('Insert Table'):
        VI[k] = "Chèn Bảng"
    elif k.startswith('Insert Text'):
        VI[k] = "Chèn Văn bản"
    elif k.startswith('Italic ({})'):
        VI[k] = "In nghiêng ({})\nLàm cho văn bản đã chọn thành in nghiêng."
    elif k.startswith('Jump to End'):
        VI[k] = "Chuyển đến Cuối\nDi chuyển con trỏ đến cuối tài liệu."
    elif k.startswith('Jump to silo'):
        VI[k] = "Chuyển đến silo 1&ndash;10"
    elif k.startswith('Keep an icon'):
        VI[k] = "Giữ biểu tượng trong khay hệ thống"
    elif k.startswith('Keep the window'):
        VI[k] = "Giữ cửa sổ ở trên tất cả"
    elif k == 'Keys':
        VI[k] = "Phím"
    elif k == 'Language' or k.startswith('Language:'):
        VI[k] = "Ngôn ngữ"
    elif k.startswith('Last Edited < 1 day'):
        VI[k] = "Chỉnh sửa lần cuối < 1 ngày"
    elif k.startswith('Last Edited < 1 hr'):
        VI[k] = "Chỉnh sửa lần cuối < 1 giờ"
    elif k.startswith('Last Edited < 1 min'):
        VI[k] = "Chỉnh sửa lần cuối < 1 phút"
    elif k.startswith('Last Edited < 49'):
        VI[k] = "Chỉnh sửa lần cuối < 49 ngày"
}

# For remaining keys, use English fallback
for k, v in entries:
    if k not in VI:
        VI[k] = v  # use EN value

# Verify we have all keys
print(f'VI translations: {len(VI)} keys')

def write_file(filename, lang_header, tr_dict):
    lines = []
    lines.append(f'"""{lang_header}"""')
    lines.append('')
    lines.append('from __future__ import annotations')
    lines.append('')
    lines.append('TRANSLATIONS: dict[str, str] = {')
    for k, v in entries:
        tv = tr_dict.get(k, v)
        k_repr = repr(k)
        v_repr = repr(tv)
        lines.append(f'    {k_repr}: {v_repr},')
    lines.append('}')
    
    path = os.path.join(d, filename)
    content = '\n'.join(lines) + '\n'
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f'{filename}: written')

# Write vi.py
write_file('vi.py', 'Ti\u1ebfng Vi\u1ec7t (Vietnamese) \u2014 483 kh\u00f3a.', VI)
print('Done')

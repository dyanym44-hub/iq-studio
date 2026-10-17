"""نافذة تحرير الصورة: تدوير، تصحيح الميلان، قص بالسحب، سطوع/تباين، أبيض وأسود، تحسين."""
from PySide6.QtCore import Qt, QRectF, QPointF, Signal
from PySide6.QtGui import QPainter, QColor, QPen
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QWidget, QPushButton, QSlider,
                               QLabel, QCheckBox, QGridLayout, QMessageBox)
from core import imaging
from ui.preview import pil_to_pixmap


class CropWidget(QWidget):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.setMinimumSize(560, 380)
        self.pm = None
        self.crop = [0.0, 0.0, 1.0, 1.0]
        self.p0 = self.p1 = None
        self.setCursor(Qt.CrossCursor)

    def set_pixmap(self, pm):
        self.pm = pm
        self.update()

    def img_rect(self):
        if not self.pm:
            return QRectF()
        s = min(self.width() / self.pm.width(), self.height() / self.pm.height())
        w, h = self.pm.width() * s, self.pm.height() * s
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def _clamp(self, pt):
        r = self.img_rect()
        return QPointF(min(max(pt.x(), r.left()), r.right()), min(max(pt.y(), r.top()), r.bottom()))

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#2b3040"))
        if not self.pm:
            return
        r = self.img_rect()
        p.drawPixmap(r.toRect(), self.pm)
        if self.p0 and self.p1:
            sel = QRectF(self.p0, self.p1).normalized()
        else:
            l, t, rr, b = self.crop
            sel = QRectF(r.left() + l * r.width(), r.top() + t * r.height(),
                         (rr - l) * r.width(), (b - t) * r.height())
        shade = QColor(0, 0, 0, 120)
        for part in (QRectF(r.left(), r.top(), r.width(), sel.top() - r.top()),
                     QRectF(r.left(), sel.bottom(), r.width(), r.bottom() - sel.bottom()),
                     QRectF(r.left(), sel.top(), sel.left() - r.left(), sel.height()),
                     QRectF(sel.right(), sel.top(), r.right() - sel.right(), sel.height())):
            p.fillRect(part, shade)
        p.setPen(QPen(QColor("#3ddc84"), 2))
        p.drawRect(sel)

    def mousePressEvent(self, e):
        self.p0 = self._clamp(e.position()); self.p1 = self.p0

    def mouseMoveEvent(self, e):
        if self.p0:
            self.p1 = self._clamp(e.position()); self.update()

    def mouseReleaseEvent(self, e):
        if not self.p0:
            return
        sel = QRectF(self.p0, self._clamp(e.position())).normalized()
        self.p0 = self.p1 = None
        r = self.img_rect()
        if sel.width() > 10 and sel.height() > 10:
            self.crop = [(sel.left() - r.left()) / r.width(), (sel.top() - r.top()) / r.height(),
                         (sel.right() - r.left()) / r.width(), (sel.bottom() - r.top()) / r.height()]
            self.changed.emit()
        self.update()


class ImageEditor(QDialog):
    def __init__(self, path, edit, ratio, parent=None):
        super().__init__(parent)
        self.setWindowTitle("تحرير الصورة — قص وتدوير وتحسين")
        self.path, self.edit, self.ratio = path, edit.copy(), ratio
        self._img_size = (1, 1)
        v = QVBoxLayout(self)
        self.crop_w = CropWidget()
        self.crop_w.changed.connect(self._crop_changed)
        v.addWidget(self.crop_w, 1)
        v.addWidget(QLabel("اسحب بالماوس على الصورة لتحديد منطقة القص. الصورة تُضبط داخل إطار البطاقة دون تشويه."))

        g = QGridLayout()
        self.s_angle = self._slider(-150, 150, int(self.edit.angle * 10))
        self.s_bri = self._slider(-100, 100, self.edit.brightness)
        self.s_con = self._slider(-100, 100, self.edit.contrast)
        self.l_angle = QLabel()
        for i, (txt, s) in enumerate((("تصحيح الميلان", self.s_angle), ("السطوع", self.s_bri), ("التباين", self.s_con))):
            g.addWidget(QLabel(txt), i, 0); g.addWidget(s, i, 1)
        g.addWidget(self.l_angle, 0, 2)
        v.addLayout(g)

        row = QHBoxLayout()
        self.c_bw = QCheckBox("أبيض وأسود"); self.c_bw.setChecked(self.edit.bw)
        self.c_en = QCheckBox("تحسين الوضوح"); self.c_en.setChecked(self.edit.enhance)
        row.addWidget(self.c_bw); row.addWidget(self.c_en); row.addStretch()
        v.addLayout(row)

        btns = QHBoxLayout()
        for txt, fn in (("تدوير 90°", self._rot), ("ملاءمة الإطار", self._fit_frame),
                        ("إلغاء القص", self._clear_crop), ("استعادة الأصل", self._reset)):
            b = QPushButton(txt); b.clicked.connect(fn); btns.addWidget(b)
        v.addLayout(btns)
        ok = QHBoxLayout()
        b_ok = QPushButton("اعتماد"); b_ok.setObjectName("primary"); b_ok.clicked.connect(self.accept)
        b_no = QPushButton("إلغاء"); b_no.clicked.connect(self.reject)
        ok.addWidget(b_ok, 2); ok.addWidget(b_no, 1)
        v.addLayout(ok)

        for s in (self.s_angle, self.s_bri, self.s_con):
            s.valueChanged.connect(self._params_changed)
        self.c_bw.toggled.connect(self._params_changed)
        self.c_en.toggled.connect(self._params_changed)
        self.resize(820, 700)
        self.refresh()

    def _slider(self, a, b, val):
        s = QSlider(Qt.Horizontal); s.setRange(a, b); s.setValue(val); return s

    def _params_changed(self):
        e = self.edit
        new_angle = self.s_angle.value() / 10
        if abs(new_angle - e.angle) > 1e-9:
            e.crop = [0.0, 0.0, 1.0, 1.0]       # تغيّر الأساس الهندسي فيُلغى القص
        e.angle = new_angle
        e.brightness, e.contrast = self.s_bri.value(), self.s_con.value()
        e.bw, e.enhance = self.c_bw.isChecked(), self.c_en.isChecked()
        self.refresh()

    def _crop_changed(self):
        self.edit.crop = self.crop_w.crop

    def _rot(self):
        self.edit.rot90 = (self.edit.rot90 + 90) % 360
        self.edit.crop = [0.0, 0.0, 1.0, 1.0]
        self.refresh()

    def _clear_crop(self):
        self.edit.crop = [0.0, 0.0, 1.0, 1.0]
        self.refresh()

    def _fit_frame(self):
        w, h = self._img_size
        a = w / h
        if a > self.ratio:
            f = self.ratio / a; self.edit.crop = [(1 - f) / 2, 0.0, (1 + f) / 2, 1.0]
        else:
            f = a / self.ratio; self.edit.crop = [0.0, (1 - f) / 2, 1.0, (1 + f) / 2]
        self.refresh()

    def _reset(self):
        from core.models import Edit
        self.edit = Edit()
        for s, v in ((self.s_angle, 0), (self.s_bri, 0), (self.s_con, 0)):
            s.blockSignals(True); s.setValue(v); s.blockSignals(False)
        for c in (self.c_bw, self.c_en):
            c.blockSignals(True); c.setChecked(False); c.blockSignals(False)
        self.refresh()

    def refresh(self):
        try:
            base = imaging.rotated_image(self.path, self.edit, 1400)
        except Exception as ex:
            QMessageBox.critical(self, "خطأ", f"تعذّر فتح الصورة:\n{ex}")
            self.reject(); return
        self._img_size = base.size
        self.l_angle.setText(f"{self.edit.angle:+.1f}°")
        self.crop_w.crop = list(self.edit.crop)
        self.crop_w.set_pixmap(pil_to_pixmap(imaging.adjust(base, self.edit)))

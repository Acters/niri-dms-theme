// SPDX-License-Identifier: MIT
#include <QApplication>
#include <QAction>
#include <QChildEvent>
#include <QDockWidget>
#include <QLayout>
#include <QLinearGradient>
#include <QPainter>
#include <QPainterPath>
#include <QProxyStyle>
#include <QRegion>
#include <QScopedValueRollback>
#include <QStyleFactory>
#include <QStyleOption>
#include <QStylePlugin>
#include <QToolBar>
#include <QToolButton>
#include <QVersionNumber>

namespace {
constexpr auto layerName = "_niriGlassMaterial";
bool activeProfile() {
    if (qEnvironmentVariable("NIRI_DMS_THEME_PROFILE") != QLatin1String("niri-dms-glass")) return false;
    const auto desktops = qEnvironmentVariable("XDG_CURRENT_DESKTOP").split(QLatin1Char(':'));
    for (const auto &desktop : desktops)
        if (desktop.compare(QLatin1String("niri"), Qt::CaseInsensitive) == 0) return true;
    return false;
}
bool drawy() { return qApp && qApp->applicationName().compare(QLatin1String("drawy"), Qt::CaseInsensitive) == 0; }
bool excluded(const QWidget *widget) {
    for (auto *w = widget; w; w = w->parentWidget()) {
        if (w->inherits("KTextEditor::View") || w->inherits("KateViewInternal") || w->inherits("Canvas")) return true;
        // A context menu/dialog is a separate surface, not editor/canvas content.
        if (w->isWindow()) break;
    }
    return false;
}
// Only background primitives and hosts with child-painted foreground may receive film.
// Dock titles are parent-painted: their layer receives the rim ONLY.
void material(QPainter *p, QRectF bounds, const QPalette &palette, qreal radius, bool edgeOnly = false) {
    if (bounds.width() < 3 || bounds.height() < 3) return;
    p->save();
    p->setRenderHint(QPainter::Antialiasing);
    const QRectF r = bounds.adjusted(.75, .75, -.75, -.75);
    radius = qMin(radius, qMin(r.width(), r.height()) / 2);
    QPainterPath shape; shape.addRoundedRect(r, radius, radius);
    p->setClipPath(shape, Qt::IntersectClip);
    const bool light = palette.color(QPalette::Window).lightness() > 128;
    if (!edgeOnly) {
        QLinearGradient film(r.topLeft(), r.bottomLeft());
        film.setColorAt(0, QColor(255,255,255,light ? 26 : 14));
        film.setColorAt(.38, QColor(255,255,255,light ? 8 : 4));
        film.setColorAt(.75, Qt::transparent);
        film.setColorAt(1, QColor(255,255,255,2));
        p->fillPath(shape, film);
        QColor accent = palette.color(QPalette::Highlight); accent.setAlpha(light ? 8 : 5);
        QLinearGradient sheen(r.topLeft(), r.bottomRight());
        sheen.setColorAt(0, accent); sheen.setColorAt(.6, Qt::transparent);
        p->fillPath(shape, sheen);
    }
    QLinearGradient rim(r.topLeft(), r.bottomRight());
    rim.setColorAt(0, QColor(255,255,255,light ? 130 : 100));
    rim.setColorAt(.3, QColor(255,255,255,light ? 60 : 48));
    rim.setColorAt(.65, QColor(255,255,255,8));
    rim.setColorAt(1, QColor(0,0,0,light ? 24 : 16));
    p->setBrush(Qt::NoBrush); p->setPen(QPen(QBrush(rim), 1)); p->drawPath(shape);
    p->restore();
}
}

class MaterialLayer final : public QWidget {
public:
    explicit MaterialLayer(QWidget *host, bool edgeOnly) : QWidget(host), m_edgeOnly(edgeOnly) {
        setObjectName(QLatin1String(layerName));
        setAttribute(Qt::WA_TransparentForMouseEvents);
        setAttribute(Qt::WA_NoSystemBackground);
        setFocusPolicy(Qt::NoFocus);
        setAutoFillBackground(false);
        host->installEventFilter(this);
        for (auto *child : host->findChildren<QWidget *>(QString(), Qt::FindDirectChildrenOnly))
            if (child != this) child->installEventFilter(this);
        setGeometry(host->rect()); show(); lower();
    }
protected:
    bool eventFilter(QObject *object, QEvent *event) override {
        if (object == parentWidget()) {
            switch (event->type()) {
            case QEvent::Resize: case QEvent::Show:
                setGeometry(parentWidget()->rect()); keepBelow(); update(); break;
            case QEvent::ChildPolished: {
                auto *child = qobject_cast<QWidget *>(static_cast<QChildEvent *>(event)->child());
                if (child && child != this) child->installEventFilter(this);
                keepBelow(); break;
            }
            case QEvent::ActionAdded: case QEvent::ActionRemoved: case QEvent::ActionChanged:
            case QEvent::PaletteChange: case QEvent::StyleChange: case QEvent::ThemeChange:
                update(); break;
            default: break;
            }
        } else if (event->type() == QEvent::ZOrderChange) keepBelow();
        return QWidget::eventFilter(object, event);
    }
    void paintEvent(QPaintEvent *) override {
        if (!activeProfile() || excluded(parentWidget())) return;
        if (auto *toolbar = qobject_cast<QToolBar *>(parentWidget())) {
            bool populated = false;
            for (auto *action : toolbar->actions()) if (action->isVisible() && !action->isSeparator()) populated = true;
            if (!populated) return; // Do not turn empty plugin toolbars into glass boxes.
        }
        QPainter p(this);
        // Dock titles are painted by the parent. Keep even rounded corner arcs
        // outside its interior: only the outer two-pixel boundary is eligible.
        if (m_edgeOnly) p.setClipRegion(QRegion(rect()).subtracted(QRegion(rect().adjusted(2,2,-2,-2))));
        material(&p, rect(), palette(), 16, m_edgeOnly);
    }
private:
    void keepBelow() { if (!m_lowering) { QScopedValueRollback<bool> guard(m_lowering, true); lower(); } }
    bool m_edgeOnly;
    bool m_lowering = false;
};

class NiriGlassStyle final : public QProxyStyle {
public:
    explicit NiriGlassStyle(QStyle *base) : QProxyStyle(base) { setObjectName(QStringLiteral("NiriGlass")); }
    using QProxyStyle::polish;
    using QProxyStyle::unpolish;
    void polish(QWidget *widget) override {
        QProxyStyle::polish(widget);
        if (!activeProfile() || excluded(widget)) return;
        const bool frame = drawy() && widget->inherits("Frame");
        const bool toolbar = qobject_cast<QToolBar *>(widget);
        const bool dock = qobject_cast<QDockWidget *>(widget);
        if ((frame || toolbar || dock) && !widget->findChild<QWidget *>(QLatin1String(layerName), Qt::FindDirectChildrenOnly))
            new MaterialLayer(widget, dock);
        auto *button = qobject_cast<QToolButton *>(widget);
        auto *parent = widget->parentWidget();
        // Drawy 1.0.2's unconnected, unmanaged menu orphan. Never affect future releases.
        if (drawy() && button && parent && parent->inherits("BottomLeftWidgets")
            && QVersionNumber::fromString(qApp->applicationVersion()) == QVersionNumber(1,0,2)
            && button->icon().name() == QLatin1String("application-menu")
            && !button->defaultAction() && !button->menu()
            && parent->layout() && parent->layout()->indexOf(button) < 0) button->hide();
    }
    void unpolish(QWidget *widget) override {
        delete widget->findChild<QWidget *>(QLatin1String(layerName), Qt::FindDirectChildrenOnly);
        QProxyStyle::unpolish(widget);
    }
    int pixelMetric(PixelMetric metric, const QStyleOption *option = nullptr, const QWidget *widget = nullptr) const override {
        // Drawy Frame interprets this as its painted radius, NOT layout padding.
        if (activeProfile() && drawy() && metric == PM_ToolBarItemMargin && widget && widget->inherits("Frame") && !excluded(widget)) return 16;
        return QProxyStyle::pixelMetric(metric, option, widget);
    }
    void drawPrimitive(PrimitiveElement element, const QStyleOption *option, QPainter *painter, const QWidget *widget = nullptr) const override {
        const bool outer = m_paintDepth == 0;
        QScopedValueRollback<int> guard(m_paintDepth, m_paintDepth + 1);
        QProxyStyle::drawPrimitive(element, option, painter, widget);
        if (!outer || !option || !activeProfile() || excluded(widget)) return;
        // A decorated host must not also get a primitive material pass.
        if (widget && widget->findChild<QWidget *>(QLatin1String(layerName), Qt::FindDirectChildrenOnly)) return;
        switch (element) {
        case PE_PanelMenu: case PE_PanelTipLabel:
            material(painter, option->rect, option->palette, 8); break;
        case PE_PanelLineEdit: case PE_FrameLineEdit:
            material(painter, option->rect, option->palette, 5); break;
        default: break;
        }
    }
    void drawControl(ControlElement element, const QStyleOption *option, QPainter *painter, const QWidget *widget = nullptr) const override {
        QScopedValueRollback<int> guard(m_paintDepth, m_paintDepth + 1);
        QProxyStyle::drawControl(element, option, painter, widget);
        // CE_Header is a composite containing section + label. Decorating the whole
        // composite would paint on its label. Its section is safe even when nested.
        if (option && activeProfile() && !excluded(widget)
            && (element == CE_HeaderSection || element == CE_HeaderEmptyArea))
            material(painter, option->rect, option->palette, 0);
    }
private:
    mutable int m_paintDepth = 0;
};

class NiriGlassStylePlugin final : public QStylePlugin {
    Q_OBJECT
    Q_PLUGIN_METADATA(IID QStyleFactoryInterface_iid FILE "niriglassstyle.json")
public:
    QStyle *create(const QString &key) override {
        if (key.compare(QLatin1String("NiriGlass"), Qt::CaseInsensitive) != 0) return nullptr;
        auto *base = QStyleFactory::create(QStringLiteral("Darkly"));
        // No substitute style: absence of the unmodified Darkly package is explicit.
        return base ? new NiriGlassStyle(base) : nullptr;
    }
};
#include "niriglassstyle.moc"

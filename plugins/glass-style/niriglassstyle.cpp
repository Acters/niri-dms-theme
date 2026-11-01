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

#include <cmath>

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
// Edge-only material is clipped to the outer two pixels, so composite controls keep
// their parent-drawn arrows, labels and state fills byte-for-byte.
void material(QPainter *p, QRectF bounds, const QPalette &palette, qreal radius, bool edgeOnly = false) {
    if (bounds.width() < 3 || bounds.height() < 3) return;
    p->save();
    p->setRenderHint(QPainter::Antialiasing);
    const QRectF r = bounds.adjusted(.75, .75, -.75, -.75);
    radius = qMin(radius, qMin(r.width(), r.height()) / 2);
    QPainterPath shape; shape.addRoundedRect(r, radius, radius);
    p->setClipPath(shape, Qt::IntersectClip);
    if (edgeOnly) {
        const QRect band = bounds.toRect();
        p->setClipRegion(QRegion(band).subtracted(QRegion(band.adjusted(2, 2, -2, -2))), Qt::IntersectClip);
    }
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
    explicit MaterialLayer(QWidget *host, bool edgeOnly, bool readable=false) : QWidget(host), m_edgeOnly(edgeOnly), m_readable(readable) {
        setObjectName(QLatin1String(layerName));
        setAttribute(Qt::WA_TransparentForMouseEvents);
        setAttribute(Qt::WA_NoSystemBackground);
        setFocusPolicy(Qt::NoFocus);
        setAutoFillBackground(false);
        host->installEventFilter(this);
        for (auto *child : host->findChildren<QWidget *>(QString(), Qt::FindDirectChildrenOnly))
            if (child != this) child->installEventFilter(this);
        syncGeometry(); show(); lower();
    }
protected:
    bool eventFilter(QObject *object, QEvent *event) override {
        if (object == parentWidget()) {
            switch (event->type()) {
            case QEvent::Resize: case QEvent::Show:
                syncGeometry(); break;
            case QEvent::ContentsRectChange:
                // A readable layer must stay inside a QFrame's content area so
                // the host-painted border is never erased.
                if (m_readable) syncGeometry();
                break;
            case QEvent::ChildPolished: {
                auto *child = qobject_cast<QWidget *>(static_cast<QChildEvent *>(event)->child());
                if (child && child != this) child->installEventFilter(this);
                keepBelow(); break;
            }
            case QEvent::ActionAdded: case QEvent::ActionRemoved: case QEvent::ActionChanged:
            case QEvent::PaletteChange: case QEvent::ThemeChange:
                update(); break;
            case QEvent::StyleChange:
                // Frame metrics can change with the style without a separate
                // contents-rect event. Toolbar/dock geometry remains full-host.
                if (m_readable) syncGeometry(); else update();
                break;
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
        if (m_readable) {
            QColor backing=palette().color(QPalette::Base);backing.setAlpha(qMax(backing.alpha(),220));
            p.setPen(Qt::NoPen);p.setBrush(backing);p.drawRoundedRect(rect(),4,4);
            return; // Below child views, never over completion text/icons.
        }
        // Dock titles are painted by the parent. Keep even rounded corner arcs
        // outside its interior: only the outer two-pixel boundary is eligible.
        if (m_edgeOnly) p.setClipRegion(QRegion(rect()).subtracted(QRegion(rect().adjusted(2,2,-2,-2))));
        material(&p, rect(), palette(), 16, m_edgeOnly);
    }
private:
    void syncGeometry() {
        setGeometry(m_readable ? parentWidget()->contentsRect() : parentWidget()->rect());
        keepBelow();
        update();
    }
    void keepBelow() { if (!m_lowering) { QScopedValueRollback<bool> guard(m_lowering, true); lower(); } }
    bool m_edgeOnly;
    bool m_readable;
    bool m_lowering = false;
};

// Gwenview's grid tooltip paints its own Highlight gradient and text in one
// paintEvent. A child film would cover that text; change only its local brush.
// The backing RGB is the better-contrast of Window and the original Highlight
// against unchanged HighlightedText, so custom schemes keep their Highlight
// RGB when Window would reduce contrast. Only alpha is raised; foreground
// roles stay untouched. Only the Highlight resolve bits are owned here.
// Externally resolved roles, locally set roles in other groups, and inherited
// roles stay untouched.
QPalette::ResolveMask highlightResolveMask() {
    static const QPalette::ResolveMask mask = [] {
        QPalette::ResolveMask bits = 0;
        for (auto group : {QPalette::Active, QPalette::Inactive, QPalette::Disabled}) {
            QPalette probe;
            probe.setResolveMask(0);
            probe.setColor(group, QPalette::Highlight, QColor());
            bits |= probe.resolveMask();
        }
        return bits;
    }();
    return mask;
}

// Actual relative-luminance contrast, not alpha, decides the local grid
// tooltip backing. Window is used only when its RGB contrasts better with the
// unchanged HighlightedText than the original Highlight RGB does.
qreal relativeLuminance(const QColor &color) {
    const auto linear = [](qreal channel) {
        return channel <= 0.04045 ? channel / 12.92 : std::pow((channel + 0.055) / 1.055, 2.4);
    };
    return 0.2126 * linear(color.redF()) + 0.7152 * linear(color.greenF()) + 0.0722 * linear(color.blueF());
}

qreal contrastRatio(const QColor &first, const QColor &second) {
    const qreal a = relativeLuminance(first);
    const qreal b = relativeLuminance(second);
    return (qMax(a, b) + 0.05) / (qMin(a, b) + 0.05);
}

class ReadableHighlight final : public QObject {
public:
    explicit ReadableHighlight(QWidget *host) : QObject(host), m_host(host) {
        setObjectName(QStringLiteral("_niriReadableHighlight"));
        m_ownedMask = highlightResolveMask();
        m_host->installEventFilter(this);
        if (auto *parent = m_host->parentWidget()) parent->installEventFilter(this);
        // An externally resolved Highlight already has an owner. Leave it alone.
        if (m_host->palette().resolveMask() & m_ownedMask) m_relinquished = true;
        else apply();
    }
    void restore() {
        if (!m_owned || m_relinquished) return;
        if (externalHighlightChanged()) { m_relinquished = true; return; }
        // Remove only the resolve bits this helper added. Any externally set
        // non-Highlight roles keep their local values and explicit ownership.
        QPalette palette = m_host->palette();
        palette.setResolveMask(palette.resolveMask() & ~m_ownedMask);
        m_writing = true;
        m_host->setPalette(palette);
        m_writing = false;
        m_owned = false;
    }
protected:
    bool eventFilter(QObject *, QEvent *event) override {
        if (event->type() != QEvent::PaletteChange) return false;
        if (m_writing || m_relinquished) return false;
        if (m_owned && externalHighlightChanged()) { m_relinquished = true; return false; }
        apply();
        return false;
    }
private:
    bool externalHighlightChanged() const {
        const QPalette palette = m_host->palette();
        if ((palette.resolveMask() & m_ownedMask) != m_ownedMask) return true;
        for (auto group : {QPalette::Active, QPalette::Inactive, QPalette::Disabled})
            if (palette.color(group, QPalette::Highlight) != m_applied.color(group, QPalette::Highlight)) return true;
        return false;
    }
    void apply() {
        if (m_relinquished) return;
        const QPalette current = m_host->palette();
        const auto currentMask = current.resolveMask();
        if (m_owned) {
            if (externalHighlightChanged()) { m_relinquished = true; return; }
        } else if (currentMask & m_ownedMask) {
            // Someone resolved a Highlight between polish and this call.
            m_relinquished = true;
            return;
        }
        QWidget *source = m_host->parentWidget() ? m_host->parentWidget() : m_host;
        QPalette wanted = current;
        for (auto group : {QPalette::Active, QPalette::Inactive, QPalette::Disabled}) {
            // Keep the text role exactly as supplied. Compare both RGB
            // candidates against it, then apply the readability alpha floor.
            const QColor ink = current.color(group, QPalette::HighlightedText);
            const QColor window = current.color(group, QPalette::Window);
            QColor color = source->palette().color(group, QPalette::Highlight);
            if (contrastRatio(ink, window) > contrastRatio(ink, color)) color = window;
            color.setAlpha(qMax(color.alpha(), 220));
            wanted.setColor(group, QPalette::Highlight, color);
        }
        wanted.setResolveMask((currentMask & ~m_ownedMask) | m_ownedMask);
        if (wanted.resolveMask() == currentMask && wanted == current) {
            m_applied = current;
            m_owned = true;
            return;
        }
        m_writing = true;
        m_host->setPalette(wanted);
        m_writing = false;
        m_applied = m_host->palette();
        m_owned = true;
    }
    QWidget *m_host;
    QPalette m_applied;
    QPalette::ResolveMask m_ownedMask = 0;
    bool m_writing = false;
    bool m_owned = false;
    bool m_relinquished = false;
};

class NiriGlassStyle final : public QProxyStyle {
public:
    explicit NiriGlassStyle(QStyle *base) : QProxyStyle(base) { setObjectName(QStringLiteral("NiriGlass")); }
    using QProxyStyle::polish;
    using QProxyStyle::unpolish;
    void polish(QWidget *widget) override {
        QProxyStyle::polish(widget);
        if (!activeProfile() || excluded(widget)) return;
        if(qApp->applicationName()==QLatin1String("gwenview") && widget->inherits("Gwenview::ToolTipWidget")
            && widget->parentWidget()
            && !widget->findChild<QObject *>(QStringLiteral("_niriReadableHighlight"),Qt::FindDirectChildrenOnly))
            new ReadableHighlight(widget);
        const bool completion = qApp->applicationName()==QLatin1String("kate") && widget->inherits("KateCompletionWidget");
        const bool frame = drawy() && widget->inherits("Frame");
        const bool toolbar = qobject_cast<QToolBar *>(widget);
        const bool dock = qobject_cast<QDockWidget *>(widget);
        if ((frame || toolbar || dock || completion) && !widget->findChild<QWidget *>(QLatin1String(layerName), Qt::FindDirectChildrenOnly))
            new MaterialLayer(widget, dock, completion);
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
        if(auto *reader=widget->findChild<QObject *>(QStringLiteral("_niriReadableHighlight"),Qt::FindDirectChildrenOnly)) {
            static_cast<ReadableHighlight *>(reader)->restore();delete reader;
        }
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
        if (element==PE_FrameTabWidget && option && activeProfile() && !excluded(widget)
            && option->palette.color(QPalette::Window).lightness()>128) {
            if (const auto *frame=qstyleoption_cast<const QStyleOptionTabWidgetFrame *>(option)) {
                QStyleOptionTabWidgetFrame lighter=*frame;
                for(auto group:{QPalette::Active,QPalette::Inactive,QPalette::Disabled})
                    for(auto role:{QPalette::Window,QPalette::Base}) {
                        QColor color=lighter.palette.color(group,role);color.setAlpha(0);lighter.palette.setColor(group,role,color);
                    }
                QProxyStyle::drawPrimitive(element,&lighter,painter,widget);return;
            }
        }
        QProxyStyle::drawPrimitive(element, option, painter, widget);
        if (!outer || !option || !activeProfile() || excluded(widget)) return;
        if (widget && qApp->applicationName()==QLatin1String("dolphin") && widget->inherits("DolphinStatusBar")
            && (element==PE_Frame || element==PE_PanelStatusBar)) {
            QColor backing=option->palette.color(QPalette::Window);backing.setAlpha(qMax(backing.alpha(),220));
            painter->save();painter->setPen(Qt::NoPen);painter->setBrush(backing);
            painter->drawRoundedRect(option->rect,5,5);painter->restore();
            return; // Status text is child-painted afterwards.
        }
        // Qt reuses QTipLabel instances without necessarily reparenting them,
        // so the old owner widget is not a reliable gate. Reading tooltips are
        // the shared-purpose exception; scope only by application and class.
        if (element==PE_PanelTipLabel && widget && qApp->applicationName()==QLatin1String("gwenview")
            && widget->inherits("QTipLabel")) {
            QColor backing=option->palette.color(QPalette::ToolTipBase);backing.setAlpha(qMax(backing.alpha(),220));
            painter->save();painter->setPen(Qt::NoPen);painter->setBrush(backing);painter->drawRoundedRect(option->rect,5,5);painter->restore();
        }
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
        const bool outer = m_paintDepth == 0;
        QScopedValueRollback<int> guard(m_paintDepth, m_paintDepth + 1);
        QProxyStyle::drawControl(element, option, painter, widget);
        if (!option || !activeProfile() || excluded(widget)) return;
        if (element == CE_HeaderSection || element == CE_HeaderEmptyArea) {
            material(painter, option->rect, option->palette, 0);
        } else if (outer && option->rect.width() >= 24 && option->rect.height() >= 20) {
            // Only the outer two pixels are eligible. The native composite, its
            // label, focus/default indication and selected interior are retained.
            if (element == CE_PushButton) {
                const auto *button = qstyleoption_cast<const QStyleOptionButton *>(option);
                if (button && !(button->features & (QStyleOptionButton::Flat | QStyleOptionButton::CommandLinkButton)))
                    material(painter, option->rect, option->palette, 4, true);
            } else if (element == CE_TabBarTab && qstyleoption_cast<const QStyleOptionTab *>(option)) {
                material(painter, option->rect, option->palette, 4, true);
            }
        }
    }
    void drawComplexControl(ComplexControl control, const QStyleOptionComplex *option, QPainter *painter, const QWidget *widget = nullptr) const override {
        const bool outer = m_paintDepth == 0;
        QScopedValueRollback<int> guard(m_paintDepth, m_paintDepth + 1);
        if (control==CC_GroupBox && option && activeProfile() && !excluded(widget)
            && option->palette.color(QPalette::Window).lightness()>128) {
            if (const auto *group=qstyleoption_cast<const QStyleOptionGroupBox *>(option)) {
                QStyleOptionGroupBox lighter=*group;
                for(auto state:{QPalette::Active,QPalette::Inactive,QPalette::Disabled})
                    for(auto role:{QPalette::Window,QPalette::Base}) {
                        QColor color=lighter.palette.color(state,role);color.setAlpha(0);lighter.palette.setColor(state,role,color);
                    }
                QProxyStyle::drawComplexControl(control,&lighter,painter,widget);return;
            }
        }
        QProxyStyle::drawComplexControl(control, option, painter, widget);
        if (!outer || !option || !activeProfile() || excluded(widget) || option->rect.width() < 24 || option->rect.height() < 20) return;
        // Parent styles draw the arrow subcontrols, text field and label after the
        // frame. Keep the material to the outer two pixels so those stay native.
        if (control == CC_ComboBox) {
            const auto *combo = qstyleoption_cast<const QStyleOptionComboBox *>(option);
            if (combo && combo->frame) material(painter, option->rect, option->palette, 4, true);
        } else if (control == CC_SpinBox) {
            const auto *spin = qstyleoption_cast<const QStyleOptionSpinBox *>(option);
            if (spin && spin->frame) material(painter, option->rect, option->palette, 4, true);
        }
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

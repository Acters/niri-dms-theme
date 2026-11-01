// SPDX-License-Identifier: MIT
#include <QApplication>
#include <QGroupBox>
#include <QTabWidget>
#include <QPushButton>
#include <QComboBox>
#include <QSpinBox>
#include <QTabBar>
#include <QAction>
#include <QDir>
#include <QDockWidget>
#include <QFile>
#include <QFrame>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QImage>
#include <QLabel>
#include <QLineEdit>
#include <QMenu>
#include <QMenuBar>
#include <QPainter>
#include <QProxyStyle>
#include <QScrollArea>
#include <QStandardItemModel>
#include <QStatusBar>
#include <QStyleFactory>
#include <QStyleOption>
#include <QTemporaryDir>
#include <QTextEdit>
#include <QTextStream>
#include <QToolBar>
#include <QToolButton>
#include <QTreeView>

class KateCompletionWidget final : public QFrame { Q_OBJECT };
class DolphinStatusBar final : public QWidget {
    Q_OBJECT
protected:
    // Composite stand-in for Dolphin's status paint: the backing primitive is
    // drawn first, then child widgets such as the scroll area and label.
    void paintEvent(QPaintEvent *) override {
        QPainter painter(this);
        QStyleOptionFrame option;
        option.rect = rect();
        option.palette = palette();
        option.state = QStyle::State_Enabled | QStyle::State_Sunken;
        style()->drawPrimitive(QStyle::PE_PanelStatusBar, &option, &painter, this);
    }
};
namespace Gwenview {
class ThumbnailBarView final : public QWidget { Q_OBJECT };
class ToolTipWidget final : public QWidget { Q_OBJECT public: using QWidget::QWidget; };
}
class QTipLabel final : public QLabel { Q_OBJECT public: using QLabel::QLabel; };
class Frame final : public QFrame {
    Q_OBJECT
};
class BottomLeftWidgets final : public QWidget {
    Q_OBJECT
};
class Canvas final : public QWidget {
    Q_OBJECT
};
class KateViewInternal final : public QWidget {
    Q_OBJECT
};
namespace KTextEditor {
class View final : public QWidget {
    Q_OBJECT
};
}
#define CHECK(condition) do { if (!(condition)) { QTextStream(stderr) << "FAIL line " << __LINE__ << ": " #condition << Qt::endl; return 1; } } while (false)
static QWidget *layer(QWidget &w) { return w.findChild<QWidget *>(QStringLiteral("_niriGlassMaterial"), Qt::FindDirectChildrenOnly); }
static QImage render(QWidget &w) {
    QImage image(w.size(), QImage::Format_ARGB32_Premultiplied); image.fill(Qt::transparent); w.render(&image); return image;
}
static QImage primitive(QStyle *style, QStyle::PrimitiveElement pe, QWidget *widget = nullptr) {
    QImage image(180, 40, QImage::Format_ARGB32_Premultiplied); image.fill(QColor(40,40,40));
    QPainter painter(&image); QStyleOptionFrame opt; opt.rect = image.rect(); opt.palette = qApp->palette(); opt.state = QStyle::State_Enabled;
    style->drawPrimitive(pe, &opt, &painter, widget); return image;
}
static QImage control(QStyle *style, QStyle::ControlElement ce, QWidget *widget = nullptr) {
    QImage image(180, 40, QImage::Format_ARGB32_Premultiplied); image.fill(QColor(40,40,40));
    QPainter painter(&image); QStyleOptionHeader opt; opt.rect = image.rect(); opt.palette = qApp->palette(); opt.state = QStyle::State_Enabled;
    style->drawControl(ce, &opt, &painter, widget); return image;
}
static QImage tipPanel(QStyle *style, QWidget *widget, const QColor &toolTipBase) {
    QImage image(180, 40, QImage::Format_ARGB32_Premultiplied); image.fill(Qt::transparent);
    QPainter painter(&image); QStyleOption opt; opt.rect = image.rect();
    opt.palette.setColor(QPalette::ToolTipBase, toolTipBase); opt.state = QStyle::State_Enabled;
    style->drawPrimitive(QStyle::PE_PanelTipLabel, &opt, &painter, widget); return image;
}
// Foreground is child-painted after the backing. Every opaque ink pixel in the
// plain render must remain exactly that color when the backing is present.
static bool inkPreserved(const QImage &glass, const QImage &plain, const QRect &area, const QColor &ink) {
    bool found = false;
    const QRect r = area.intersected(QRect(QPoint(0,0), plain.size())).intersected(QRect(QPoint(0,0), glass.size()));
    for (int y = r.top(); y <= r.bottom(); ++y)
        for (int x = r.left(); x <= r.right(); ++x)
            if (plain.pixelColor(x, y) == ink) {
                if (glass.pixelColor(x, y) != ink) return false;
                found = true;
            }
    return found;
}
int main(int argc, char **argv) {
    // Darkly/KConfig may initialize configuration while constructing its style.
    // Keep all native-test state away from live user files (including initial startup).
    QTemporaryDir home;
    CHECK(home.isValid());
    if (qEnvironmentVariable("NIRI_GLASS_TEST_HOME") != QLatin1String("1")) {
        qputenv("HOME", home.path().toUtf8());
        qputenv("XDG_CONFIG_HOME", (home.path() + QStringLiteral("/config")).toUtf8());
        qputenv("XDG_CACHE_HOME", (home.path() + QStringLiteral("/cache")).toUtf8());
        qputenv("XDG_DATA_HOME", (home.path() + QStringLiteral("/data")).toUtf8());
        qputenv("XDG_STATE_HOME", (home.path() + QStringLiteral("/state")).toUtf8());
        QDir().mkpath(home.path() + QStringLiteral("/config"));
    }
    qputenv("NIRI_DMS_THEME_PROFILE", "niri-dms-glass");
    qputenv("XDG_CURRENT_DESKTOP", "niri");
    QApplication app(argc, argv);
    // CTest sets QT_PLUGIN_PATH; also support invoking build/style-test directly.
    app.addLibraryPath(QCoreApplication::applicationDirPath() + QStringLiteral("/plugins"));
    app.setApplicationName(QStringLiteral("drawy")); app.setApplicationVersion(QStringLiteral("1.0.2"));
    auto *style = QStyleFactory::create(QStringLiteral("NiriGlass")); CHECK(style);
    app.setStyle(style);
    auto *proxy = qobject_cast<QProxyStyle *>(style); CHECK(proxy);
    CHECK(proxy->baseStyle()->objectName().contains(QStringLiteral("darkly"), Qt::CaseInsensitive));
    // Keep fixture windows separate from the existing animation-sensitive pixel suite.
    if (app.arguments().contains(QStringLiteral("--readability"))) {
    // Isolated readability exceptions: match app AND exact surface, never global roles.
    for (const QColor color : {QColor(247,249,255,26), QColor(0,0,0,26)}) {
        app.setApplicationName(QStringLiteral("kate"));
        KateCompletionWidget completion; completion.resize(250,100);
        QPalette pal=completion.palette();pal.setColor(QPalette::Base,color);completion.setPalette(pal);
        completion.ensurePolished();CHECK(layer(completion));
        CHECK(completion.palette()==pal);
        const QImage backing=render(*layer(completion));
        CHECK(backing.pixelColor(80,50).alpha()>=220);
        CHECK(layer(completion)->testAttribute(Qt::WA_TransparentForMouseEvents));
        app.setApplicationName(QStringLiteral("other"));
        KateCompletionWidget unrelated;unrelated.ensurePolished();CHECK(!layer(unrelated));
        app.setApplicationName(QStringLiteral("dolphin"));
        DolphinStatusBar status; const QPalette original=status.palette();
        for (auto pe : {QStyle::PE_Frame,QStyle::PE_PanelStatusBar}) {
            QImage result(180,40,QImage::Format_ARGB32_Premultiplied);result.fill(Qt::transparent);
            QPainter painter(&result);QStyleOptionFrame opt;opt.rect=result.rect();opt.palette.setColor(QPalette::Window,color);opt.palette.setColor(QPalette::Base,color);opt.state=QStyle::State_Enabled|QStyle::State_Sunken;
            style->drawPrimitive(pe,&opt,&painter,&status);painter.end();
            CHECK(result.pixelColor(80,20).alpha()>=220);CHECK(status.palette()==original);
        }
        app.setApplicationName(QStringLiteral("gwenview"));
        const bool lightSurface = color.lightness() > 128;
        const QColor tooltipInk = lightSurface ? QColor(Qt::black) : QColor(Qt::white);
        const QColor changedWindow = lightSurface ? QColor(240,242,248,26) : QColor(8,9,12,26);
        const auto windowBacking = [](const QColor &window) {
            return QColor(window.red(), window.green(), window.blue(), 220);
        };
        QWidget viewport;QPalette viewPalette=viewport.palette();
        viewPalette.setColor(QPalette::Highlight,QColor(40,90,220,26));viewPalette.setColor(QPalette::Window,color);
        viewPalette.setColor(QPalette::HighlightedText,tooltipInk);viewport.setPalette(viewPalette);
        Gwenview::ToolTipWidget gridTip(&viewport);const QColor text=gridTip.palette().color(QPalette::HighlightedText);
        gridTip.ensurePolished();
        // Window wins for both the light black-ink and dark white-ink themes.
        CHECK(gridTip.palette().color(QPalette::Highlight)==windowBacking(color));
        CHECK(gridTip.palette().color(QPalette::HighlightedText)==text);CHECK(viewport.palette()==viewPalette);
        viewPalette.setColor(QPalette::Highlight,QColor(120,50,180,26));viewPalette.setColor(QPalette::Window,changedWindow);viewport.setPalette(viewPalette);
        CHECK(gridTip.palette().color(QPalette::Highlight)==windowBacking(changedWindow));
        CHECK(gridTip.palette().color(QPalette::Window)==changedWindow);
        CHECK(gridTip.palette().color(QPalette::HighlightedText)==text);
        style->unpolish(&gridTip);CHECK(!gridTip.testAttribute(Qt::WA_SetPalette));CHECK(gridTip.palette()==viewport.palette());
        Gwenview::ThumbnailBarView strip;QTipLabel tip(&strip);
        QImage result(180,40,QImage::Format_ARGB32_Premultiplied);result.fill(Qt::transparent);
        QPainter painter(&result);QStyleOption opt;opt.rect=result.rect();opt.palette.setColor(QPalette::ToolTipBase,color);
        style->drawPrimitive(QStyle::PE_PanelTipLabel,&opt,&painter,&tip);painter.end();
        CHECK(result.pixelColor(80,20).alpha()>=220);

        // Kate composite: a real QFrame border plus a child QTreeView and label.
        // The readable layer must be inset to contentsRect so the box border and
        // all child-painted ink survive, while the alpha-26 backing is visible.
        {
            app.setApplicationName(QStringLiteral("kate"));
            QStandardItemModel model;
            model.setHorizontalHeaderLabels({QStringLiteral("Kind"),QStringLiteral("Candidate")});
            for (const auto &row : {QStringLiteral("method"),QStringLiteral("member"),QStringLiteral("class")}) {
                auto *first = new QStandardItem(row); first->setForeground(QColor(Qt::black));
                auto *second = new QStandardItem(row + QStringLiteral(" completion")); second->setForeground(QColor(Qt::black));
                model.appendRow({first, second});
            }
            KateCompletionWidget box;
            box.setFrameShape(QFrame::Box);
            box.setLineWidth(1);
            box.resize(340, 210);
            QPalette boxPalette = box.palette();
            boxPalette.setColor(QPalette::Base, color);
            box.setPalette(boxPalette);
            auto *boxLabel = new QLabel(QStringLiteral("Completion candidate"), &box);
            QPalette labelPalette = boxLabel->palette();
            labelPalette.setColor(QPalette::Window, Qt::white);
            labelPalette.setColor(QPalette::WindowText, Qt::black);
            boxLabel->setPalette(labelPalette);
            boxLabel->setAutoFillBackground(true);
            boxLabel->setGeometry(box.contentsRect().left()+12, box.contentsRect().top()+8, 220, 22);
            auto *tree = new QTreeView(&box);
            tree->setFrameShape(QFrame::NoFrame);
            tree->setRootIsDecorated(false);
            tree->setAlternatingRowColors(false);
            tree->setModel(&model);
            QPalette treePalette = tree->palette();
            treePalette.setColor(QPalette::Base, color);
            treePalette.setColor(QPalette::Text, Qt::black);
            tree->setPalette(treePalette);
            tree->setGeometry(box.contentsRect().left()+12, box.contentsRect().top()+36,
                              box.contentsRect().width()-24, box.contentsRect().height()-48);
            box.show(); app.processEvents();
            CHECK(layer(box));
            CHECK(layer(box)->geometry() == box.contentsRect());
            CHECK(box.contentsRect() != box.rect());
            CHECK(box.children().indexOf(layer(box)) < box.children().indexOf(tree));
            const QImage withBacking = render(box);
            layer(box)->hide();
            const QImage withoutBacking = render(box);
            layer(box)->show();
            CHECK(withBacking.pixelColor(4,4).alpha() >= 220);
            // QFrame's own one-pixel border is byte-for-byte native.
            for (int x=0; x<withBacking.width(); ++x)
                CHECK(withBacking.pixelColor(x,0) == withoutBacking.pixelColor(x,0)
                      && withBacking.pixelColor(x,withBacking.height()-1) == withoutBacking.pixelColor(x,withoutBacking.height()-1));
            for (int y=0; y<withBacking.height(); ++y)
                CHECK(withBacking.pixelColor(0,y) == withoutBacking.pixelColor(0,y)
                      && withBacking.pixelColor(withBacking.width()-1,y) == withoutBacking.pixelColor(withBacking.width()-1,y));
            CHECK(inkPreserved(withBacking, withoutBacking, boxLabel->geometry(), QColor(Qt::black)));
            CHECK(inkPreserved(withBacking, withoutBacking, tree->geometry(), QColor(Qt::black)));
            box.resize(380, 230); app.processEvents();
            CHECK(layer(box)->geometry() == box.contentsRect());
            box.setContentsMargins(5,5,5,5); app.processEvents();
            CHECK(layer(box)->geometry() == box.contentsRect());
            const int oldLineWidth = box.lineWidth();
            box.setLineWidth(oldLineWidth + 2); app.processEvents();
            CHECK(layer(box)->geometry() == box.contentsRect());
        }

        // Dolphin composite: backing primitive then a scroll-area label. The
        // label's own pixels stay identical and the backing remains visible
        // around it.
        {
            app.setApplicationName(QStringLiteral("dolphin"));
            DolphinStatusBar bar; bar.resize(340, 110);
            QPalette barPalette = bar.palette();
            barPalette.setColor(QPalette::Window, color);
            bar.setPalette(barPalette);
            auto *scroll = new QScrollArea(&bar);
            scroll->setFrameShape(QFrame::NoFrame);
            scroll->setGeometry(14,12,312,86);
            auto *statusLabel = new QLabel(QStringLiteral("Ready - 42 items - 12.4 GiB"));
            QPalette statusPalette = statusLabel->palette();
            statusPalette.setColor(QPalette::Window, Qt::white);
            statusPalette.setColor(QPalette::WindowText, Qt::black);
            statusLabel->setPalette(statusPalette);
            statusLabel->setAutoFillBackground(true);
            statusLabel->resize(300,50);
            scroll->setWidget(statusLabel);
            bar.show(); app.processEvents();
            const QImage glass = render(bar);
            const QRect labelRect(statusLabel->mapTo(&bar, QPoint(0,0)), statusLabel->size());
            CHECK(glass.pixelColor(4,4).alpha() >= 220);
            CHECK(inkPreserved(glass, glass, labelRect, QColor(Qt::black)));
            app.setApplicationName(QStringLiteral("other"));
            const QImage native = render(bar);
            app.setApplicationName(QStringLiteral("dolphin"));
            CHECK(inkPreserved(glass, native, labelRect, QColor(Qt::black)));
        }

        // External non-Highlight roles must survive parent palette changes and
        // unpolish; only the Highlight bits owned by the helper are removed.
        {
            app.setApplicationName(QStringLiteral("gwenview"));
            QWidget toolHost;
            QPalette hostPalette = toolHost.palette();
            hostPalette.setColor(QPalette::Highlight, QColor(40,90,220,26));
            hostPalette.setColor(QPalette::Window, color);
            hostPalette.setColor(QPalette::HighlightedText, tooltipInk);
            toolHost.setPalette(hostPalette);
            Gwenview::ToolTipWidget externalTip(&toolHost);
            externalTip.ensurePolished();
            CHECK(externalTip.palette().color(QPalette::Highlight) == windowBacking(color));
            QPalette externalPalette = externalTip.palette();
            externalPalette.setColor(QPalette::Text, QColor(11,22,33));
            externalPalette.setColor(QPalette::WindowText, QColor(44,55,66));
            externalTip.setPalette(externalPalette);
            CHECK(externalTip.palette().color(QPalette::Text) == QColor(11,22,33));
            hostPalette.setColor(QPalette::Highlight, QColor(120,50,180,26));
            hostPalette.setColor(QPalette::Window, changedWindow);
            toolHost.setPalette(hostPalette);
            CHECK(externalTip.palette().color(QPalette::Text) == QColor(11,22,33));
            CHECK(externalTip.palette().color(QPalette::WindowText) == QColor(44,55,66));
            CHECK(externalTip.palette().color(QPalette::Highlight) == windowBacking(changedWindow));
            CHECK(externalTip.palette().color(QPalette::Window) == changedWindow);
            for (auto group : {QPalette::Active, QPalette::Inactive, QPalette::Disabled})
                CHECK(externalTip.palette().color(group, QPalette::Window) == toolHost.palette().color(group, QPalette::Window));
            style->unpolish(&externalTip);
            CHECK(externalTip.palette().color(QPalette::Text) == QColor(11,22,33));
            CHECK(externalTip.palette().color(QPalette::WindowText) == QColor(44,55,66));
            CHECK(externalTip.palette().color(QPalette::Highlight) == QColor(120,50,180,26));
            CHECK(externalTip.testAttribute(Qt::WA_SetPalette));
        }

        // External Highlight ownership: once the host writes a different
        // Highlight, parent updates stop and unpolish leaves the user role.
        {
            app.setApplicationName(QStringLiteral("gwenview"));
            QWidget toolHost;
            QPalette hostPalette = toolHost.palette();
            hostPalette.setColor(QPalette::Highlight, QColor(40,90,220,26));
            hostPalette.setColor(QPalette::Window, color);
            hostPalette.setColor(QPalette::HighlightedText, tooltipInk);
            toolHost.setPalette(hostPalette);
            Gwenview::ToolTipWidget userTip(&toolHost);
            userTip.ensurePolished();
            CHECK(userTip.palette().color(QPalette::Highlight) == windowBacking(color));
            QPalette userPalette = userTip.palette();
            userPalette.setColor(QPalette::Highlight, QColor(210,60,50,255));
            userTip.setPalette(userPalette);
            CHECK(userTip.palette().color(QPalette::Highlight) == QColor(210,60,50,255));
            hostPalette.setColor(QPalette::Highlight, QColor(0,200,100,26));
            toolHost.setPalette(hostPalette);
            CHECK(userTip.palette().color(QPalette::Highlight) == QColor(210,60,50,255));
            style->unpolish(&userTip);
            CHECK(userTip.palette().color(QPalette::Highlight) == QColor(210,60,50,255));
            CHECK(userTip.testAttribute(Qt::WA_SetPalette));
        }

        // QTipLabel's owner is not a stable gate: Qt reuses the label for other
        // owners without reparenting. In Gwenview the app-wide class exception
        // applies; the same label in another application gets no backing.
        {
            app.setApplicationName(QStringLiteral("gwenview"));
            QWidget plainOwner;
            QTipLabel reused(&plainOwner);
            CHECK(tipPanel(style,&reused,color).pixelColor(80,20).alpha() >= 220);
            QTipLabel ownerless;
            CHECK(tipPanel(style,&ownerless,color).pixelColor(80,20).alpha() >= 220);
            Gwenview::ThumbnailBarView strip2;
            QTipLabel stripTip(&strip2);
            CHECK(tipPanel(style,&stripTip,color).pixelColor(80,20).alpha() >= 220);
            // The reused label is painted for its original owner. The old owner
            // widget is not consulted; only application and QTipLabel class are.
            CHECK(tipPanel(style,&reused,color).pixelColor(80,20).alpha() >= 220);
            app.setApplicationName(QStringLiteral("dolphin"));
            CHECK(tipPanel(style,&reused,color).pixelColor(80,20).alpha() < 220);
            app.setApplicationName(QStringLiteral("gwenview"));
        }
    }
    // Custom user schemes keep their original Highlight when Window would give
    // less contrast with the unchanged white HighlightedText (Breeze Light).
    {
        app.setApplicationName(QStringLiteral("gwenview"));
        QWidget customHost;
        QPalette customPalette = customHost.palette();
        customPalette.setColor(QPalette::Window, QColor(239,240,241,26));
        customPalette.setColor(QPalette::Highlight, QColor(61,174,233,26));
        customPalette.setColor(QPalette::HighlightedText, QColor(Qt::white));
        customHost.setPalette(customPalette);
        Gwenview::ToolTipWidget customTip(&customHost);
        customTip.ensurePolished();
        CHECK(customTip.palette().color(QPalette::Highlight) == QColor(61,174,233,220));
        CHECK(customTip.palette().color(QPalette::HighlightedText) == QColor(Qt::white));
        style->unpolish(&customTip);
    }
    QTextStream(stdout)<<"PASS: synthetic Kate completion, Dolphin Small/FullWidth, Gwenview strip tooltip backing; contrast-selected light/dark Window backing and custom Highlight fallback; local palette preservation; composite frame/child ink and ownership fixtures"<<Qt::endl;
    return 0;
    }
    // All apps retain native palette colors and alpha; material is decorative only.
    for (const auto &name : {QStringLiteral("kate"),QStringLiteral("dolphin"),QStringLiteral("drawy")}) {
        app.setApplicationName(name);
        for (const auto &window : {QColor(247,249,255,26),QColor(0,0,0,26)}) {
            QPalette source=app.palette(); source.setColor(QPalette::Window,window);
            QPalette native=source,glass=source;
            proxy->baseStyle()->polish(native); style->polish(glass);
            CHECK(glass==native);
        }
    }
    app.setApplicationName(QStringLiteral("drawy"));
    qunsetenv("NIRI_DMS_THEME_PROFILE");
    auto *unmarkedFactory = QStyleFactory::create(QStringLiteral("NiriGlass")); CHECK(unmarkedFactory);
    CHECK(primitive(unmarkedFactory,QStyle::PE_PanelMenu) == primitive(proxy->baseStyle(),QStyle::PE_PanelMenu));
    delete unmarkedFactory;
    Frame inactive; inactive.ensurePolished(); CHECK(!layer(inactive));
    CHECK(style->pixelMetric(QStyle::PM_ToolBarItemMargin, nullptr, &inactive) == proxy->baseStyle()->pixelMetric(QStyle::PM_ToolBarItemMargin, nullptr, &inactive));
    CHECK(primitive(style, QStyle::PE_PanelMenu) == primitive(proxy->baseStyle(), QStyle::PE_PanelMenu));
    qputenv("NIRI_DMS_THEME_PROFILE", "niri-dms-glass"); qputenv("XDG_CURRENT_DESKTOP", "COSMIC");
    Frame cosmic; cosmic.ensurePolished(); CHECK(!layer(cosmic));
    CHECK(primitive(style, QStyle::PE_PanelMenu) == primitive(proxy->baseStyle(), QStyle::PE_PanelMenu));
    qputenv("XDG_CURRENT_DESKTOP", "notniri"); Frame substring; substring.ensurePolished(); CHECK(!layer(substring));
    qputenv("XDG_CURRENT_DESKTOP", "NIRI:Wayland");
    Frame frame; frame.resize(220,100); frame.show(); app.processEvents(); CHECK(layer(frame));
    CHECK(style->pixelMetric(QStyle::PM_ToolBarItemMargin, nullptr, &frame) == 16);
    for (auto metric : {QStyle::PM_LayoutLeftMargin, QStyle::PM_LayoutRightMargin, QStyle::PM_LayoutTopMargin, QStyle::PM_LayoutBottomMargin, QStyle::PM_DefaultFrameWidth})
        CHECK(style->pixelMetric(metric,nullptr,&frame) == proxy->baseStyle()->pixelMetric(metric,nullptr,&frame));
    QFrame ordinary; ordinary.ensurePolished(); CHECK(!layer(ordinary));
    CHECK(style->pixelMetric(QStyle::PM_ToolBarItemMargin, nullptr, &ordinary) == proxy->baseStyle()->pixelMetric(QStyle::PM_ToolBarItemMargin, nullptr, &ordinary));
    CHECK(layer(frame)->geometry() == frame.rect());
    CHECK(layer(frame)->testAttribute(Qt::WA_TransparentForMouseEvents)); CHECK(layer(frame)->focusPolicy() == Qt::NoFocus);
    auto *label = new QLabel(QStringLiteral("Opaque foreground"), &frame);
    label->setGeometry(30,30,160,30); label->setAutoFillBackground(true);
    QPalette textPalette = label->palette(); textPalette.setColor(QPalette::Window, Qt::white); textPalette.setColor(QPalette::WindowText, Qt::black); label->setPalette(textPalette); label->show();
    app.processEvents();
    const QImage foreground = render(frame).copy(label->geometry());
    layer(frame)->hide(); CHECK(render(frame).copy(label->geometry()) == foreground); layer(frame)->show();
    bool opaqueInk = false; for (int y=0;y<foreground.height();++y) for (int x=0;x<foreground.width();++x) if (foreground.pixelColor(x,y) == QColor(Qt::black)) opaqueInk = true;
    CHECK(opaqueInk);
    label->lower(); app.processEvents(); CHECK(frame.children().indexOf(layer(frame)) < frame.children().indexOf(label));
    CHECK(frame.childAt(label->geometry().center()) == label);
    frame.resize(280,110); app.processEvents(); CHECK(layer(frame)->geometry() == frame.rect());
    QImage film = render(*layer(frame)); CHECK(film.pixelColor(0,0).alpha() == 0); CHECK(film.pixelColor(25,3).alpha() > 0);
    auto beforePalette = render(*layer(frame)); QPalette light = frame.palette(); light.setColor(QPalette::Window, frame.palette().color(QPalette::Window).lightness() > 128 ? Qt::black : Qt::white); frame.setPalette(light); app.processEvents(); CHECK(render(*layer(frame)) != beforePalette);

    QToolBar emptyToolbar; emptyToolbar.resize(240,40); emptyToolbar.show(); app.processEvents(); CHECK(layer(emptyToolbar));
    const QImage emptyFilm = render(*layer(emptyToolbar));
    for (int y=0;y<emptyFilm.height();++y) for (int x=0;x<emptyFilm.width();++x) CHECK(emptyFilm.pixelColor(x,y).alpha()==0);
    QToolBar toolbar; toolbar.resize(240,70); auto *button = new QToolButton(&toolbar); button->setText(QStringLiteral("Tool")); toolbar.addWidget(button); toolbar.show(); app.processEvents();
    CHECK(layer(toolbar)); CHECK(toolbar.children().indexOf(layer(toolbar)) < toolbar.children().indexOf(button));
    QPalette buttonPalette = button->palette(); const QColor ink(17,23,31);
    for (auto role : {QPalette::WindowText, QPalette::ButtonText, QPalette::Text}) buttonPalette.setColor(role, ink);
    button->setPalette(buttonPalette);
    const QImage buttonPixels = render(toolbar).copy(button->geometry());
    layer(toolbar)->hide(); const QImage plainButton = render(toolbar).copy(button->geometry()); layer(toolbar)->show();
    bool buttonInk = false;
    for (int y=0;y<plainButton.height();++y) for (int x=0;x<plainButton.width();++x)
        if (plainButton.pixelColor(x,y) == ink) { CHECK(buttonPixels.pixelColor(x,y) == ink); buttonInk = true; }
    CHECK(buttonInk);
    QDockWidget dock(QStringLiteral("Parent-painted title must stay intact")); dock.resize(400,140); dock.show(); app.processEvents(); CHECK(layer(dock));
    const QImage dockMaterial = render(dock); layer(dock)->hide(); const QImage dockPlain = render(dock);
    CHECK(dockMaterial.copy(2,2,396,136) == dockPlain.copy(2,2,396,136)); CHECK(dockMaterial != dockPlain);

    QLabel plainLabel; QMenuBar menuBar; QStatusBar status; QTextEdit editor; QLineEdit field; QHeaderView header(Qt::Horizontal);
    for (QWidget *w : {static_cast<QWidget *>(&plainLabel), static_cast<QWidget *>(&ordinary), static_cast<QWidget *>(&menuBar), static_cast<QWidget *>(&status), static_cast<QWidget *>(&editor), static_cast<QWidget *>(&field), static_cast<QWidget *>(&header)}) { w->ensurePolished(); CHECK(!layer(*w)); }
    Canvas canvas; KateViewInternal kate; KTextEditor::View view;
    for (QWidget *host : {static_cast<QWidget *>(&canvas), static_cast<QWidget *>(&kate), static_cast<QWidget *>(&view)}) {
        QToolBar excludedToolbar(host); excludedToolbar.ensurePolished(); CHECK(!layer(excludedToolbar));
        QLineEdit internal(host); internal.ensurePolished(); CHECK(primitive(style, QStyle::PE_PanelLineEdit, &internal) == primitive(proxy->baseStyle(), QStyle::PE_PanelLineEdit, &internal));
        CHECK(control(style, QStyle::CE_HeaderSection, &internal) == control(proxy->baseStyle(), QStyle::CE_HeaderSection, &internal));
        QMenu popup(host); popup.ensurePolished();
        CHECK(primitive(style, QStyle::PE_PanelMenu, &popup) != primitive(proxy->baseStyle(), QStyle::PE_PanelMenu, &popup));
    }
    for (auto pe : {QStyle::PE_PanelMenu, QStyle::PE_PanelTipLabel, QStyle::PE_FrameLineEdit, QStyle::PE_PanelLineEdit}) CHECK(primitive(style, pe) != primitive(proxy->baseStyle(), pe));
    for (auto ce : {QStyle::CE_HeaderSection, QStyle::CE_HeaderEmptyArea}) CHECK(control(style, ce) != control(proxy->baseStyle(), ce));
    // Composite control rims must never modify their text/arrows/state interiors.
    const QPalette originalPalette=app.palette();
    for (bool dark : {false,true}) {
        QPalette pal=originalPalette;
        pal.setColor(QPalette::Window,dark?QColor(0,0,0,26):QColor(247,249,255,26));
        pal.setColor(QPalette::Button,pal.color(QPalette::Window));
        app.setPalette(pal);
        QPushButton push(QStringLiteral("Opaque button")); push.setCheckable(true); push.resize(180,36);
        QComboBox combo; combo.addItems({QStringLiteral("Choice"),QStringLiteral("Other")}); combo.resize(180,36);
        QSpinBox spin; spin.setRange(0,100); spin.setValue(42); spin.resize(180,36);
        QTabBar tabs; tabs.addTab(QStringLiteral("First")); tabs.addTab(QStringLiteral("Second")); tabs.resize(240,36);
        // Isolate the new composite-frame pass from the already-tested line-edit film.
        for (auto *line : spin.findChildren<QLineEdit *>()) line->setStyle(proxy->baseStyle());
        for (QWidget *widget : {static_cast<QWidget *>(&push),static_cast<QWidget *>(&combo),static_cast<QWidget *>(&spin),static_cast<QWidget *>(&tabs)}) {
            widget->show(); app.processEvents();
            for (int state=0;state<3;++state) {
                widget->setEnabled(state!=2); push.setChecked(state==1); tabs.setCurrentIndex(state==1?1:0);
                qputenv("XDG_CURRENT_DESKTOP","COSMIC"); widget->update(); app.processEvents(); const QImage native=render(*widget);
                qputenv("XDG_CURRENT_DESKTOP","niri"); widget->update(); app.processEvents(); const QImage glass=render(*widget);
                CHECK(glass!=native);
                if(widget==&tabs) {
                    for(int i=0;i<tabs.count();++i) {
                        const QRect inside=tabs.tabRect(i).adjusted(2,2,-2,-2);
                        CHECK(glass.copy(inside)==native.copy(inside));
                    }
                } else {
                    const QRect inside=widget->rect().adjusted(2,2,-2,-2);
                    CHECK(glass.copy(inside)==native.copy(inside));
                }
            }
        }
    }
    app.setPalette(originalPalette); qputenv("XDG_CURRENT_DESKTOP","niri");
    // Light-only structural fill removal: native foreground and dark mode stay intact.
    for (bool dark : {false,true}) {
        QPalette pal=originalPalette;
        const QColor backing=dark?QColor(0,0,0,26):QColor(247,249,255,26);
        pal.setColor(QPalette::Window,backing); pal.setColor(QPalette::Base,backing);
        app.setPalette(pal);
        QGroupBox group(QStringLiteral("Structural label")); group.resize(240,120); group.show();
        QTabWidget pages; pages.resize(260,160); pages.addTab(new QWidget,QStringLiteral("First")); pages.addTab(new QWidget,QStringLiteral("Second")); pages.show();
        app.processEvents();
        for (QWidget *widget : {static_cast<QWidget *>(&group),static_cast<QWidget *>(&pages)}) {
            qputenv("XDG_CURRENT_DESKTOP","COSMIC"); widget->update(); app.processEvents(); const QImage native=render(*widget);
            qputenv("XDG_CURRENT_DESKTOP","niri"); widget->update(); app.processEvents(); const QImage glass=render(*widget);
            const QPoint sample(widget->width()/2,widget->height()*3/4);
            if(dark) {
                // The tab rim is an existing active-profile effect; compare the pane.
                const QRect area=widget==&pages?QRect(2,40,widget->width()-4,widget->height()-42):widget->rect();
                CHECK(glass.copy(area)==native.copy(area));
            } else CHECK(glass.pixelColor(sample).alpha()<native.pixelColor(sample).alpha());
        }
        for (QWidget *host : {static_cast<QWidget *>(&canvas),static_cast<QWidget *>(&kate),static_cast<QWidget *>(&view)}) {
            QGroupBox inside(QStringLiteral("Protected content"),host); inside.resize(180,70);inside.ensurePolished();
            qputenv("XDG_CURRENT_DESKTOP","COSMIC");const QImage native=render(inside);
            qputenv("XDG_CURRENT_DESKTOP","niri");CHECK(render(inside)==native);
        }
    }
    app.setPalette(originalPalette);qputenv("XDG_CURRENT_DESKTOP","niri");
    // drawItemText remains byte-for-byte native: no opacity or palette rewriting.
    QImage nativeText(220,40,QImage::Format_ARGB32_Premultiplied); nativeText.fill(Qt::white); QImage glassText = nativeText;
    { QPainter p(&nativeText); proxy->baseStyle()->drawItemText(&p,nativeText.rect(),Qt::AlignCenter,app.palette(),true,QStringLiteral("Native text"),QPalette::Text); }
    { QPainter p(&glassText); style->drawItemText(&p,glassText.rect(),Qt::AlignCenter,app.palette(),true,QStringLiteral("Native text"),QPalette::Text); }
    CHECK(nativeText == glassText);

    // Isolated named icon theme avoids depending on the user's installed icon themes.
    QTemporaryDir icons; CHECK(icons.isValid()); QDir().mkpath(icons.path()+QStringLiteral("/test/16x16/actions"));
    QFile index(icons.path()+QStringLiteral("/test/index.theme")); CHECK(index.open(QIODevice::WriteOnly));
    index.write("[Icon Theme]\nName=Test\nDirectories=16x16/actions\n[16x16/actions]\nSize=16\nType=Fixed\nContext=Actions\n"); index.close();
    QImage iconImage(16,16,QImage::Format_ARGB32); iconImage.fill(Qt::black); CHECK(iconImage.save(icons.path()+QStringLiteral("/test/16x16/actions/application-menu.png")));
    QIcon::setThemeSearchPaths({icons.path()}); QIcon::setThemeName(QStringLiteral("test"));
    const QIcon icon = QIcon::fromTheme(QStringLiteral("application-menu")); CHECK(icon.name() == QStringLiteral("application-menu"));
    BottomLeftWidgets bottom; auto *layout = new QHBoxLayout(&bottom);
    auto *orphan = new QToolButton(&bottom); orphan->setIcon(icon);
    auto *managed = new QToolButton(&bottom); managed->setIcon(icon); layout->addWidget(managed);
    auto *connected = new QToolButton(&bottom); connected->setIcon(icon); connected->setDefaultAction(new QAction(icon, QStringLiteral("Real action"), &bottom));
    auto *withMenu = new QToolButton(&bottom); withMenu->setIcon(icon); withMenu->setMenu(new QMenu(withMenu));
    bottom.show(); app.processEvents(); CHECK(orphan->isHidden()); CHECK(managed->isVisible()); CHECK(connected->isVisible()); CHECK(withMenu->isVisible());
    app.setApplicationVersion(QStringLiteral("1.0.3"));
    BottomLeftWidgets future; new QHBoxLayout(&future); auto *futureButton = new QToolButton(&future); futureButton->setIcon(icon); future.show(); app.processEvents(); CHECK(futureButton->isVisible());
    app.setApplicationName(QStringLiteral("other-app")); app.setApplicationVersion(QStringLiteral("1.0.2"));
    Frame unrelated; unrelated.ensurePolished(); CHECK(!layer(unrelated)); CHECK(style->pixelMetric(QStyle::PM_ToolBarItemMargin,nullptr,&unrelated) != 16);
    BottomLeftWidgets other; new QHBoxLayout(&other); auto *otherButton = new QToolButton(&other); otherButton->setIcon(icon); other.show(); app.processEvents(); CHECK(otherButton->isVisible());
    style->unpolish(&frame); CHECK(!layer(frame));
    QTextStream(stdout) << "PASS: scoped activation, rounded Drawy frames, stock metrics, safe hosts/exclusions, layer input/z-order/resize/theme, untouched foreground, exact orphan guard" << Qt::endl;
    return 0;
}
#include "style-test.moc"

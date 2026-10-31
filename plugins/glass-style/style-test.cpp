// SPDX-License-Identifier: MIT
#include <QApplication>
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
#include <QStatusBar>
#include <QStyleFactory>
#include <QStyleOption>
#include <QTemporaryDir>
#include <QTextEdit>
#include <QTextStream>
#include <QToolBar>
#include <QToolButton>

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

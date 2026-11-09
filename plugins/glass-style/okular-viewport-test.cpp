// SPDX-License-Identifier: MIT
#include <QApplication>
#include <QAbstractScrollArea>
#include <QDir>
#include <QImage>
#include <QPainter>
#include <QScrollArea>
#include <QStyleFactory>
#include <QStyle>
#include <QTemporaryDir>
#include <QTextStream>

// Same public widget/paint contract as Okular's document viewport; no PDF input.
class PageView final : public QAbstractScrollArea {
    Q_OBJECT
public:
    PageView(bool opaque=true, bool noBackground=true) {
        viewport()->setAttribute(Qt::WA_OpaquePaintEvent,opaque);
        viewport()->setAttribute(Qt::WA_NoSystemBackground,noBackground);
        viewport()->setAutoFillBackground(false);
    }
protected:
    void paintEvent(QPaintEvent *) override {
        QPainter painter(viewport());
        painter.fillRect(viewport()->rect(),viewport()->palette().color(QPalette::Dark));
        painter.fillRect(QRect(30,10,80,90),QColor(249,241,223));
        painter.fillRect(QRect(45,25,40,15),QColor(17,53,121));
    }
};
#define CHECK(c) do { if (!(c)) { QTextStream(stderr)<<"FAIL "<<__LINE__<<": " #c<<Qt::endl;return 1; } } while(false)
static QObject *fix(QWidget *viewport) { return viewport->findChild<QObject *>(QStringLiteral("_niriOkularViewport"),Qt::FindDirectChildrenOnly); }
static QImage render(QWidget &widget) {
    QImage image(widget.size(),QImage::Format_ARGB32_Premultiplied);image.fill(Qt::transparent);widget.render(&image);return image;
}
static bool inkUnchanged(const QImage &first,const QImage &second,QColor ink) {
    bool found=false;
    for(int y=0;y<first.height();++y)for(int x=0;x<first.width();++x)
        if(first.pixelColor(x,y)==ink) {found=true;if(second.pixelColor(x,y)!=ink)return false;}
    return found;
}
int main(int argc,char **argv) {
    QTemporaryDir home;CHECK(home.isValid());
    qputenv("HOME",home.path().toUtf8());
    for(const auto *root:{"XDG_CONFIG_HOME","XDG_CACHE_HOME","XDG_DATA_HOME","XDG_STATE_HOME"})
        qputenv(root,(home.path()+QLatin1Char('/')+QLatin1String(root)).toUtf8());
    qputenv("QT_QPA_PLATFORMTHEME","generic");qputenv("QT_QPA_PLATFORMTHEME_QT6","generic");
    qputenv("NIRI_DMS_THEME_PROFILE","niri-dms-glass");qputenv("XDG_CURRENT_DESKTOP","niri");
    QApplication app(argc,argv);app.setApplicationName(QStringLiteral("okular"));
    app.addLibraryPath(QCoreApplication::applicationDirPath()+QStringLiteral("/plugins"));
    auto *style=QStyleFactory::create(QStringLiteral("NiriGlass"));CHECK(style);app.setStyle(style);
    for(const QColor color:{QColor(0,0,0,26),QColor(247,249,255,26),QColor(0,0,0,0)})
        for(bool opaque:{false,true})for(bool noBackground:{false,true}) {
            PageView page(opaque,noBackground);page.resize(240,160);
            QPalette palette=page.palette();palette.setColor(QPalette::Dark,color);page.setPalette(palette);
            page.ensurePolished();page.viewport()->ensurePolished();
            CHECK(fix(page.viewport()));CHECK(!page.viewport()->testAttribute(Qt::WA_OpaquePaintEvent));
            CHECK(page.viewport()->testAttribute(Qt::WA_NoSystemBackground)==noBackground);
            CHECK(!page.viewport()->autoFillBackground());CHECK(page.palette()==palette);
            CHECK(page.viewport()->findChildren<QWidget *>(QString(),Qt::FindDirectChildrenOnly).isEmpty());
            const QImage corrected=render(page);
            style->polish(&page);CHECK(page.viewport()->findChildren<QObject *>(QStringLiteral("_niriOkularViewport"),Qt::FindDirectChildrenOnly).size()==1);
            style->unpolish(&page);CHECK(!fix(page.viewport()));
            CHECK(page.viewport()->testAttribute(Qt::WA_OpaquePaintEvent)==opaque);
            CHECK(page.viewport()->testAttribute(Qt::WA_NoSystemBackground)==noBackground);
            const QImage native=render(page);
            CHECK(inkUnchanged(corrected,native,QColor(17,53,121)));
            CHECK(inkUnchanged(corrected,native,QColor(249,241,223)));
        }
    PageView changing;QPalette palette=changing.palette();
    palette.setColor(QPalette::Dark,QColor(20,30,40,255));changing.setPalette(palette);
    changing.ensurePolished();changing.viewport()->ensurePolished();CHECK(changing.viewport()->testAttribute(Qt::WA_OpaquePaintEvent));
    palette.setColor(QPalette::Dark,QColor(20,30,40,26));changing.setPalette(palette);
    CHECK(!changing.viewport()->testAttribute(Qt::WA_OpaquePaintEvent));CHECK(changing.viewport()->testAttribute(Qt::WA_NoSystemBackground));
    palette.setColor(QPalette::Dark,QColor(20,30,40,255));changing.setPalette(palette);CHECK(changing.viewport()->testAttribute(Qt::WA_OpaquePaintEvent));
    palette.setColor(QPalette::Dark,QColor(20,30,40,26));changing.setPalette(palette);
    changing.viewport()->setAttribute(Qt::WA_OpaquePaintEvent,true);
    QEvent shown(QEvent::Show);QApplication::sendEvent(changing.viewport(),&shown);CHECK(!changing.viewport()->testAttribute(Qt::WA_OpaquePaintEvent));
    style->unpolish(changing.viewport());CHECK(changing.viewport()->testAttribute(Qt::WA_OpaquePaintEvent));
    QScrollArea unrelated;unrelated.viewport()->setAttribute(Qt::WA_OpaquePaintEvent,true);
    unrelated.ensurePolished();unrelated.viewport()->ensurePolished();CHECK(!fix(unrelated.viewport()));CHECK(unrelated.viewport()->testAttribute(Qt::WA_OpaquePaintEvent));
    app.setApplicationName(QStringLiteral("other"));PageView other;other.ensurePolished();other.viewport()->ensurePolished();CHECK(!fix(other.viewport()));CHECK(other.viewport()->testAttribute(Qt::WA_OpaquePaintEvent));
    app.setApplicationName(QStringLiteral("okular"));qputenv("XDG_CURRENT_DESKTOP","COSMIC");
    PageView outside;outside.ensurePolished();outside.viewport()->ensurePolished();CHECK(!fix(outside.viewport()));CHECK(outside.viewport()->testAttribute(Qt::WA_OpaquePaintEvent));
    qputenv("XDG_CURRENT_DESKTOP","niri");qunsetenv("NIRI_DMS_THEME_PROFILE");
    PageView unmarked;unmarked.ensurePolished();unmarked.viewport()->ensurePolished();CHECK(!fix(unmarked.viewport()));CHECK(unmarked.viewport()->testAttribute(Qt::WA_OpaquePaintEvent));
    QTextStream(stdout)<<"Okular viewport scope, lifecycle, palette and document-pixel checks passed."<<Qt::endl;return 0;
}
#include "okular-viewport-test.moc"

#include <QApplication>
#include <QAction>
#include <QFrame>
#include <QHBoxLayout>
#include <QProxyStyle>
#include <QToolButton>
#include <QTextStream>
class Frame final : public QFrame {
    Q_OBJECT
};
class BottomLeftWidgets final : public QWidget {
    Q_OBJECT
};
int main(int argc,char **argv) {
    QApplication app(argc,argv);
    app.setApplicationVersion(QStringLiteral("1.0.2"));
    Frame drawyFrame; QFrame ordinaryFrame;
    auto *proxy=qobject_cast<QProxyStyle *>(app.style());
    const int radius=app.style()->pixelMetric(QStyle::PM_ToolBarItemMargin,nullptr,&drawyFrame);
    const int normal=app.style()->pixelMetric(QStyle::PM_ToolBarItemMargin,nullptr,&ordinaryFrame);
    if(radius!=16 || normal!=2 || !proxy || !proxy->baseStyle()->objectName().contains("darkly",Qt::CaseInsensitive)) return 1;

    BottomLeftWidgets bottom;
    auto *layout=new QHBoxLayout(&bottom);
    auto *orphan=new QToolButton(&bottom); orphan->setIcon(QIcon::fromTheme(QStringLiteral("application-menu")));
    auto *managed=new QToolButton(&bottom); managed->setIcon(orphan->icon()); layout->addWidget(managed);
    auto *connected=new QToolButton(&bottom); connected->setIcon(orphan->icon());
    connected->setDefaultAction(new QAction(orphan->icon(),QStringLiteral("Connected"),&bottom));
    QWidget top; auto *topLayout=new QHBoxLayout(&top);
    auto *realMenu=new QToolButton(&top); realMenu->setIcon(orphan->icon()); topLayout->addWidget(realMenu);
    bottom.show(); top.show(); app.processEvents();
    QTextStream(stdout) << "Orphan hidden=" << orphan->isHidden()
        << " managed visible=" << managed->isVisible()
        << " connected visible=" << connected->isVisible()
        << " real menu visible=" << realMenu->isVisible() << Qt::endl;
    if(!orphan->isHidden() || !managed->isVisible() || !connected->isVisible() || !realMenu->isVisible()) return 2;

    app.setApplicationVersion(QStringLiteral("1.0.3"));
    BottomLeftWidgets future; auto *futureLayout=new QHBoxLayout(&future);
    auto *placeholder=new QWidget(&future); futureLayout->addWidget(placeholder);
    auto *futureMenu=new QToolButton(&future); futureMenu->setIcon(orphan->icon());
    future.show(); app.processEvents();
    if(!futureMenu->isVisible()) return 3;
    QTextStream(stdout) << "PASS: only the 1.0.2 unmanaged orphan is hidden; other controls and future versions are untouched; rounded frames retained" << Qt::endl;
    return 0;
}
#include "style-test.moc"

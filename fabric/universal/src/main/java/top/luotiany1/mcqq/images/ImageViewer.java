package top.luotiany1.mcqq.images;

/** Loader-independent viewer geometry. Coordinates are GUI-scaled pixels. */
public final class ImageViewer {
    public record Rect(double x,double y,double width,double height) {
        public boolean contains(double px,double py) { return px>=x && px<x+width && py>=y && py<y+height; }
    }
    private final int sourceWidth,sourceHeight;
    private final Rect origin;
    private final long started;
    private double zoom=1, panX,panY, lastX,lastY;
    private boolean dragging;
    public ImageViewer(int width,int height,Rect origin,long now) {
        if(width<=0 || height<=0)throw new IllegalArgumentException("Invalid image dimensions");
        this.sourceWidth=width; this.sourceHeight=height; this.origin=origin; this.started=now;
    }
    public Rect viewport(int screenWidth,int screenHeight) {
        double fit=Math.min(1,Math.min(Math.max(1,screenWidth-64.0)/sourceWidth,Math.max(1,screenHeight-64.0)/sourceHeight));
        double w=Math.max(1,sourceWidth*fit),h=Math.max(1,sourceHeight*fit);
        return new Rect((screenWidth-w)/2,(screenHeight-h)/2,w,h);
    }
    public Rect image(int screenWidth,int screenHeight) {
        Rect v=viewport(screenWidth,screenHeight); clamp(v);
        double w=v.width*zoom,h=v.height*zoom;
        return new Rect(v.x+(v.width-w)/2+panX,v.y+(v.height-h)/2+panY,w,h);
    }
    public Rect animated(int screenWidth,int screenHeight,long now) {
        Rect end=image(screenWidth,screenHeight);
        double p=Math.max(0,Math.min(1,(now-started)/240.0)); p=1-Math.pow(1-p,3);
        return new Rect(origin.x+(end.x-origin.x)*p,origin.y+(end.y-origin.y)*p,
            origin.width+(end.width-origin.width)*p,origin.height+(end.height-origin.height)*p);
    }
    public double progress(long now) { return Math.max(0,Math.min(1,(now-started)/240.0)); }
    public boolean press(double x,double y,int button,int width,int height) {
        if(button!=0)return false;
        if(!viewport(width,height).contains(x,y))return false;
        dragging=true; lastX=x; lastY=y; return true;
    }
    public void drag(double x,double y,int width,int height) {
        if(!dragging)return;
        panX+=x-lastX; panY+=y-lastY; lastX=x; lastY=y; clamp(viewport(width,height));
    }
    public void release() { dragging=false; }
    public void scroll(double x,double y,double amount,int width,int height) {
        Rect v=viewport(width,height); if(!v.contains(x,y) || amount==0)return;
        Rect old=image(width,height); double ix=(x-old.x)/old.width, iy=(y-old.y)/old.height;
        zoom=Math.max(1,Math.min(8,zoom*Math.pow(1.2,amount)));
        double w=v.width*zoom,h=v.height*zoom;
        panX=x-ix*w-(v.x+(v.width-w)/2); panY=y-iy*h-(v.y+(v.height-h)/2);
        clamp(v);
    }
    private void clamp(Rect v) {
        double x=Math.max(0,(v.width*zoom-v.width)/2),y=Math.max(0,(v.height*zoom-v.height)/2);
        panX=Math.max(-x,Math.min(x,panX)); panY=Math.max(-y,Math.min(y,panY));
    }
}

package top.luotiany1.mcqq.images;

public final class ViewerProbe {
    public static void main(String[] args) {
        var start=new ImageViewer.Rect(10,20,30,40);
        var viewer=new ImageViewer(1600,800,start,1000);
        var viewport=viewer.viewport(1000,700);
        if(viewport.width()!=936 || viewport.height()!=468)throw new AssertionError("Viewport must fit original aspect ratio");
        if(!viewer.animated(1000,700,1000).equals(start))throw new AssertionError("Animation must begin at thumbnail");
        if(!viewer.animated(1000,700,1240).equals(viewer.image(1000,700)))throw new AssertionError("Animation must end at centered image");
        viewer.press(500,350,0,1000,700); viewer.drag(900,650,1000,700); viewer.release();
        if(!viewer.image(1000,700).equals(viewport))throw new AssertionError("Unzoomed image must not pan");
        viewer.scroll(500,350,4,1000,700);
        viewer.press(500,350,0,1000,700); viewer.drag(5000,5000,1000,700); viewer.release();
        var moved=viewer.image(1000,700);
        if(moved.x()>viewport.x()+0.001 || moved.y()>viewport.y()+0.001)throw new AssertionError("Pan exposed empty space at edge");
        viewer.scroll(500,350,-100,1000,700);
        if(!viewer.image(1000,700).equals(viewport))throw new AssertionError("Zooming out must restore bounds");
        var small=new ImageViewer(100,50,start,0).viewport(1000,700);
        if(small.width()!=100 || small.height()!=50)throw new AssertionError("Viewport must honor source dimensions");
        System.out.println("PASS: viewer animation, original-size viewport, cursor zoom and pan bounds");
    }
}

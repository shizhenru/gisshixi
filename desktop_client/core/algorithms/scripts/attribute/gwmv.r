#GW indicators for validicating multi-source spatial data sets,
#including the localized versions of ME, MAE,MRE, RMSE
gwmv <- function (data, valid.locat, vars,
                  kernel = "bisquare", adaptive = FALSE, 
                  bw, p = 2, theta = 0, longlat = F, dMat,
                  quantile = FALSE) 
{
    if (is(data, "Spatial")) {
    p4s <- proj4string(data)
    dp.locat <- coordinates(data)
  }
  else if (is(data, "data.frame") && (!missing(dMat))) 
    data <- data
  else if (inherits(data, "sf"))
  {
    p4s <- st_crs(data)$proj4string
    if(any((st_geometry_type(data)=="POLYGON")) | any(st_geometry_type(data)=="MULTIPOLYGON"))
      dp.locat <- st_coordinates(st_centroid(st_geometry(data)))
    else
      dp.locat <- st_coordinates(st_geometry(data))
  }
  else stop("Given data must be a Spatial*DataFrame or data.frame object")
  if (missing(valid.locat)) {
    sp.given <- FALSE
    valid.locat <- data
    vp.locat <- dp.locat
  }
  else {
    sp.given <- T
    if (is(valid.locat, "Spatial")) 
      vp.locat <- coordinates(valid.locat)
    else if (inherits(valid.locat, "sf"))
    {
      if (any((st_geometry_type(valid.locat)=="POLYGON")) | any(st_geometry_type(valid.locat)=="MULTIPOLYGON"))
         vp.locat <- st_coordinates(st_centroid(st_geometry(valid.locat)))
      else
         vp.locat<- st_coordinates(valid.locat)
    }
    else {
      warning("Output loactions are not packed in a Spatial object,and it has to be a two-column numeric vector")
      valid.locat <- data
    }
  }
  if(inherits(data, "sf"))
    data <- st_drop_geometry(data)
  else
    data <- as(data, "data.frame")
  dp.n <- nrow(data)
  sp.n <- nrow(vp.locat)
  if (missing(dMat)) 
    DM.given <- F
  else {
    DM.given <- T
    dim.dMat <- dim(dMat)
    if (dim.dMat[1] != dp.n || dim.dMat[2] != sp.n) 
      stop("Dimensions of dMat are not correct")
  }
  len.var <- 0  
  if (missing(vars)) 
    stop("Variables input error")
  else {
     len.var <- length(vars)
     if(len.var < 2)
       stop("At least two variables are included for validation")
  }
  if (missing(bw) || bw <= 0) 
    stop("Bandwidth is not specified incorrectly")
  
  col.nm <- colnames(data)
  var.idx <- match(vars, col.nm)[!is.na(match(vars, col.nm))]
  if (length(var.idx) != len.var) 
    stop("Variables input doesn't match with data")
  x <- data[, var.idx]
  x <- as.matrix(x)
  var.nms <- names(data)[var.idx]
  var.n <- ncol(x)
  # Global indicators
  ME <- matrix(0, nrow=var.n, ncol=var.n)
  MRE <- matrix(0, nrow=var.n, ncol=var.n)
  MAE <- matrix(0, nrow=var.n, ncol=var.n)
  RMSE <- matrix(0, nrow=var.n, ncol=var.n)
  
  for (i in 1:var.n) {
    for (j in 1:var.n) {
      if (i != j) {
        diff <- x[, i] - x[, j]
        abs_diff <- abs(diff)
        ME[i, j] <- mean(diff)
        if (any(x[, j] == 0)) {
          MRE[i, j] <- NA
        }
        else {
           MRE[i, j] <- mean(abs_diff / x[, j])
        }
        MAE[i, j] <- mean(abs_diff)
        RMSE[i, j] <- sqrt(mean(diff^2))
      }
    }
  }
  ME.nms <- c()
  MAE.nms <- c()
  MRE.nms <- c()
  RMSE.nms <- c()
  for (i in 1:var.n) {
        me.v1v2 <- paste("ME", var.nms[i], sep = "_")
        mae.v1v2 <- paste("MAE", var.nms[i], sep = "_")
        mre.v1v2 <- paste("MRE", var.nms[i], sep = "_")
        rmse.v1v2 <- paste("RMSE",var.nms[i], sep = "_")
        ME.nms <- c(ME.nms,me.v1v2)
        MAE.nms <- c(MAE.nms, mae.v1v2)
        MRE.nms <- c(MRE.nms, mre.v1v2)
        RMSE.nms <- c(RMSE.nms, rmse.v1v2)
  }
    colnames(ME) <- ME.nms
    rownames(ME) <- var.nms
    colnames(MAE) <- MAE.nms
    rownames(MAE) <- var.nms
    colnames(MRE) <- MRE.nms
    rownames(MRE) <- var.nms
    colnames(RMSE) <- RMSE.nms
    rownames(RMSE) <- var.nms
    print(ME)
    ###GW indicators
  GW_ME <- matrix(numeric((var.n - 1) * var.n * sp.n/2), 
                    nrow = sp.n)
  GW_MAE <- matrix(numeric((var.n - 1) * var.n * sp.n/2), 
                    nrow = sp.n)
  GW_MRE <- matrix(numeric((var.n - 1) * var.n * sp.n/2), 
                    nrow = sp.n)
  GW_RMSE <- matrix(numeric((var.n - 1) * var.n * sp.n/2), 
                    nrow = sp.n)
  for (i in 1:sp.n) {
    if (DM.given) 
      dist.vi <- dMat[, i]
    else {
      if (sp.given) 
        dist.vi <- gw.dist(dp.locat, valid.locat, focus = i, 
                           p, theta, longlat)
      else dist.vi <- gw.dist(dp.locat = dp.locat, focus = i, 
                              p = p, theta = theta, longlat = longlat)
    }
    W.i <- matrix(gw.weight(dist.vi, bw, kernel, adaptive), 
                  nrow = 1)
    sum.w <- sum(W.i)
    Wi <- W.i/sum.w
    tag <- 0
    for (j in 1:(var.n - 1)) 
       for (k in (j + 1):var.n) {
        tag <- tag + 1
        diff <- x[, j] - x[, k]
        abs_diff <- abs(diff)
        GW_ME[i,tag] <- sum(diff*Wi)
        GW_MAE[i,tag] <- sum(abs_diff*Wi)
        if (any(x[, j] == 0)) {
          GW_MRE[i, tag] <- NA
        }
        else {
           GW_MRE[i,tag] <- sum((abs_diff/x[,j])*Wi)
        }
        GW_RMSE[i,tag] <- sqrt(sum(diff^2*Wi))
      }
  }
  gwme.nms <- c()
  gwmae.nms <- c()
  gwmre.nms <- c()
  gwrmse.nms <- c()
  for (j in 1:(var.n - 1)) 
       for (k in (j + 1):var.n)
  {
     gwme.nms <- c(gwme.nms, paste(paste("LME", sep = "_", var.nms[j]), sep = "_", var.nms[k]))
     gwmae.nms <- c(gwmae.nms, paste(paste("LMAE", sep = "_", var.nms[j]), sep = "_", var.nms[k]))
     gwmre.nms <- c(gwmre.nms, paste(paste("LMRE", sep = "_", var.nms[j]), sep = "_", var.nms[k]))
     gwrmse.nms <- c(gwrmse.nms, paste(paste("LRMSE", sep = "_", var.nms[j]), sep = "_", var.nms[k]))
  }
  colnames(GW_ME) <- gwme.nms 
  colnames(GW_MAE) <- gwmae.nms 
  colnames(GW_MRE) <- gwmre.nms
  colnames(GW_RMSE) <- gwrmse.nms 
  res.df <- data.frame(GW_ME, GW_MAE, GW_MRE, GW_RMSE)
  rownames(res.df) <- rownames(valid.locat)
  griddedObj <- F
  if (is(valid.locat, "Spatial"))
  { 
    if (is(valid.locat, "SpatialPolygonsDataFrame")) 
    {
      polygons <- polygons(valid.locat)
      SDF <- SpatialPolygonsDataFrame(Sr = polygons, data = res.df,
                                      match.ID = F)
    }
    else
    {
      griddedObj <- gridded(valid.locat)
      SDF <- SpatialPointsDataFrame(coords = valid.locat, data = res.df, 
                                       proj4string = CRS(p4s), match.ID=F)
      gridded(SDF) <- griddedObj
    }
  }
  else if(inherits(valid.locat, "sf"))
  {
     SDF <- st_sf(res.df, geometry = st_geometry(valid.locat))
  }
  else
    SDF <- SpatialPointsDataFrame(coords = valid.locat, data = res.df, 
                                       proj4string = CRS(p4s), match.ID=F) 
  res <- list(SDF = SDF, vars = vars, kernel = kernel, adaptive = adaptive, 
              bw = bw, p = p, theta = theta, longlat = longlat, DM.given = DM.given, 
              sp.given = sp.given, ME=ME, MAE=MAE, MRE=MRE, RMSE=RMSE)
  class(res) <- "gwmv"
  invisible(res)
}

print.gwmv<-function(x, ...)
{
    if (!inherits(x, "gwmv")) 
        stop("It's not a lss object")
    cat("   ***********************************************************************\n")
    cat("   *                       Package   GWmodel                             *\n")
    cat("   ***********************************************************************\n")
    cat("\n   ***********************Calibration information*************************\n")
    vars <- x$vars
    var.n <- length(vars)
    cat("\n   Local validation indicators calculated for variables:")
    cat("\n   ", vars)
    dp.n <- nrow(data.frame(x$SDF))
    cat("\n   Number of validation points:", dp.n)
    cat("\n   Kernel function:", x$kernel, "\n")
    if (x$sp.given) 
        cat("   Validation points: A seperate set of validation points is used.\n")
    else cat("   Validation points: the same locations as observations are used.\n")
    if (x$adaptive) 
        cat("   Adaptive bandwidth: ", x$bw, " (number of nearest neighbours)\n", 
            sep = "")
    else cat("   Fixed bandwidth:", x$bw, "\n")
    if (x$DM.given) 
        cat("   Distance metric: A distance matrix is specified for this model calibration.\n")
    else {
        if (x$longlat) 
            cat("   Distance metric: Great Circle distance metric is used.\n")
        else if (x$p == 2) 
            cat("   Distance metric: Euclidean distance metric is used.\n")
        else if (x$p == 1) 
            cat("   Distance metric: Manhattan distance metric is used.\n")
        else if (is.infinite(x$p)) 
            cat("   Distance metric: Chebyshev distance metric is used.\n")
        else cat("   Distance metric: A generalized Minkowski distance metric is used with p=", 
            x$p, ".\n")
        if (x$theta != 0 && x$GW.agruments$p != 2 && !x$longlat) 
            cat("   Coordinate rotation: The coordinate system is rotated by an angle", 
                x$theta, "in radian.\n")
    }
    cat("\n   ************************Global validation Statistics:**********************\n")
    cat("   Global mean errors(ME):\n")
    print(x$ME)
    cat("   Global mean absolute error(MAE):\n")
    print(x$MAE)
    cat("   Global mean relative error(MRE):\n")
    print(x$MRE)
    cat("   Global root mean square error(RMSE):\n")
    print(x$RMSE)

    cat("\n   ************************Local validation Statistics:**********************\n")
    if(inherits(x$SDF, "Spatial"))
       df0 <- as(x$SDF, "data.frame")
    else
       df0 <- st_drop_geometry(x$SDF)
    var.nms <- vars
     gwme.nms <- c()
     gwmae.nms <- c()
     gwmre.nms <- c()
     gwrmse.nms <- c()
     for (j in 1:(var.n - 1)) 
       for (k in (j + 1):var.n)
    {
     gwme.nms <- c(gwme.nms, paste(paste("LME", sep = "_", var.nms[j]), sep = "_", var.nms[k]))
     gwmae.nms <- c(gwmae.nms, paste(paste("LMAE", sep = "_", var.nms[j]), sep = "_", var.nms[k]))
     gwmre.nms <- c(gwmre.nms, paste(paste("LMRE", sep = "_", var.nms[j]), sep = "_", var.nms[k]))
     gwrmse.nms <- c(gwrmse.nms, paste(paste("LRMSE", sep = "_", var.nms[j]), sep = "_", var.nms[k]))
    }
    cat("   Summary information for Local ME:\n")
    df.LME <- data.frame(df0[, gwme.nms])
    LME.sum <- t(apply(df.LME, 2, summary))[, c(1:3, 5, 6)]
    if(var.n==2){
       cat(gwme.nms, ":\n")
       print(LME.sum)
    }
    else {
       rownames(LME.sum) <- gwme.nms
       printCoefmat(LME.sum)
    }
    cat("   Summary information for Local MAE:\n")
    df.LMAE <- data.frame(df0[, gwmae.nms])
    LMAE.sum <- t(apply(df.LMAE, 2, summary))[, c(1:3, 5, 6)]
    
    if(var.n==2){
       cat(gwmae.nms, ":\n")
       print(LMAE.sum)
    }
    else{
        rownames(LMAE.sum) <- gwmae.nms
        printCoefmat(LMAE.sum)
    }
    cat("   Summary information for Local MRE:\n")
    df.LMRE <- data.frame(df0[, gwmre.nms])
    LMRE.sum <- t(apply(df.LMRE, 2, summary))[, c(1:3, 5, 6)]
    if(var.n==2){
       cat(gwmre.nms, ":\n")
       print(LMRE.sum)
    }
    else{
    rownames(LMRE.sum) <- gwmre.nms
    printCoefmat(LMRE.sum)
    }
    cat("   Summary information for Local RMSE:\n")
    df.RMSE <- data.frame(df0[, gwrmse.nms])
    LRMSE.sum <- t(apply(df.RMSE, 2, summary))[, c(1:3, 5, 6)]
     if(var.n==2){
       cat(gwrmse.nms, ":\n")
       print(LRMSE.sum)
    }
    else {
       rownames(LRMSE.sum) <- gwrmse.nms
       printCoefmat(LRMSE.sum)
    }
	cat("\n   ************************************************************************\n")
	invisible(x)
}    

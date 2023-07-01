#imports
import numpy as np
import math
import time
import cv2
import bot_env as screen

def locate_color(image, boundaries=[([180, 0, 180], [220, 20, 220])], DEBUG=False):
    # define the list of boundaries
    # loop over the boundaries
    for (lower, upper) in boundaries:
        # create NumPy arrays from the boundaries
        lower = np.array(lower, dtype="uint8")
        upper = np.array(upper, dtype="uint8")

        # find the colors within the specified boundaries and apply the mask
        mask = cv2.inRange(image, lower, upper)
        output = cv2.bitwise_and(image, image, mask=mask)
        ret, thresh = cv2.threshold(mask, 40, 255, 0)
        contours, hierarchy = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)

    if DEBUG:
            cv2.imwrite("images/Locate_Image_DebugPRE.png", image)

    if len(contours) != 0:
        # find the biggest countour by the area -> usually implies the closest contour to the camera
        c = max(contours, key=cv2.contourArea)
        x, y, w, h = cv2.boundingRect(c)

        # The biggest contour will be drawn with a green outline
        image = cv2.rectangle(image, pt1=(x, y), pt2=(x+w, y+h), color=(0, 255, 0), thickness=2)
        image = cv2.drawContours(image, contours, 0, color=(0,255,0), thickness=2)
        mask = np.zeros(image.shape[:2], np.uint8)
        for cont in contours:
            x_c, y_c, w_c, h_c = cv2.boundingRect(cont)
            if mask[y_c + int(round(h_c/2)), x_c + int(round(w_c/2))] != 255:
                mask[y_c:y_c+h_c,x_c:x_c+w_c] = 255
                if(x != x_c or y != y_c or w != w_c or h != h_c):
                    # Other contours will be highlighted with the opposite color of upper for visibility
                    image = cv2.rectangle(image, pt1=(x_c, y_c), pt2=(x_c+w_c, y_c+h_c), color=(0,0,255), thickness=2)
        # Center of the contour
        x_center, y_center = (math.floor(x+w/2), math.floor(y+h/2))
        click_radius = math.floor(min(w, h)/2)

        if DEBUG:
            cv2.imwrite("images/Locate_Image_DebugPOST.png", image)
            print('Length of contours: %d'%(len(contours)))
            print(x, y, w, h)

        return [x_center, y_center]
    else:
        return []
    

def locate_image(img_rgb, filename, threshold=0.7, name='Screenshot', DEBUG_1=False, DEBUG_2=False):
    try:
        img_gray = cv2.cvtColor(img_rgb, cv2.COLOR_BGR2GRAY)
        template = cv2.imread('images/' + filename, 0)
        w, h = template.shape[::-1]
        pt = None
        res = cv2.matchTemplate(img_gray, template, cv2.TM_CCOEFF_NORMED)
        loc = np.where(res >= threshold)
        items = []
        # Add a mask to remove duplicate matches
        mask = np.zeros(img_rgb.shape[:2], np.uint8)
        for pt in zip(*loc[::-1]):
            # Add a circle to mark a match
            if DEBUG_2:
                cv2.rectangle(img_rgb, pt, (pt[0] + w, pt[1] + h), (255, 0, 0), thickness=1)
            if mask[pt[1] + int(round(h/2)), pt[0] + int(round(w/2))] != 255:
                mask[pt[1]:pt[1]+h, pt[0]:pt[0]+w] = 255
                # An array of points
                items.append([pt[0]+math.floor(w/2), pt[1]+math.floor(h/2)])
                if DEBUG_1:
                    cv2.circle(img_rgb, (pt[0]+math.floor(w/2), pt[1]+math.floor(h/2)), radius=min(math.floor(w/3), math.floor(h/3)), color=(0,255,0), thickness=1)
        if DEBUG_2:
            cv2.imshow(name, np.hstack([img_rgb]))
            cv2.waitKey(0)
            time.sleep(0.5)
        if len(items) > 0:
            return items
        print('Locate image could not find the image')
        return []
    except:
        print('Locate image failed!')
        return []
    

def get_action_text(client_rect, DEBUG=False):
    scale = 300
    # I don't identify the locaiton of the fishing/mining/woodcutting text since I havent trained on the osrs font, 
    # make sure it's dragged to the top-left area!
    screen.screen_image([client_rect[0]+25, client_rect[1]+50, 100, 30], 'Session_Action.png')
    img = screen.resize_image(cv2.imread('images/Session_Action.png'), scale)
    if DEBUG:
        debug_view(img)

    # Need to mask for green and red 
    boundaries=[([0, 250, 0], [10, 255, 10])]
    boundaries_not=[([0, 0, 250], [10, 10, 255])]
    for (lower, upper) in boundaries:
        # create NumPy arrays from the boundaries
        lower = np.array(lower, dtype="uint8")
        upper = np.array(upper, dtype="uint8")
        img_g = copy.deepcopy(img)
        # find the colors within the specified boundaries and apply the mask
        mask_g = cv2.inRange(img_g, lower, upper)
        output = cv2.bitwise_and(img_g, img_g, mask=mask_g)
        ret, thresh_g = cv2.threshold(mask_g, 40, 255, 0)

    for (lower, upper) in boundaries_not:
        # create NumPy arrays from the boundaries
        lower = np.array(lower, dtype="uint8")
        upper = np.array(upper, dtype="uint8")
        img_r = copy.deepcopy(img)
        # find the colors within the specified boundaries and apply the mask
        mask_r = cv2.inRange(img_r, lower, upper)
        output = cv2.bitwise_and(img_r, img_r, mask=mask_r)
        ret, thresh_r = cv2.threshold(mask_r, 40, 255, 0)
    
    # Specify structure shape and kernel size.
    # Kernel size increases or decreases the area
    # of the rectangle to be detected.
    # A smaller value like (10, 10) will detect
    # each word instead of a sentence.
    rect_kernel_g = cv2.getStructuringElement(cv2.MORPH_RECT, (10, 10))
    rect_kernel_r = cv2.getStructuringElement(cv2.MORPH_RECT, (20, 20))
    
    # Applying dilation on the threshold image
    dilation_g = cv2.dilate(thresh_g, rect_kernel_g, iterations = 1)
    dilation_r = cv2.dilate(thresh_r, rect_kernel_r, iterations = 1)
    
    # Finding contours
    contours_g, hierarchy = cv2.findContours(dilation_g, cv2.RETR_EXTERNAL,
                                                    cv2.CHAIN_APPROX_NONE)
    contours_r, hierarchy = cv2.findContours(dilation_r, cv2.RETR_EXTERNAL,
                                                    cv2.CHAIN_APPROX_NONE)
    if DEBUG:
        draw_contour = cv2.drawContours(copy.deepcopy(img), contours_g, 0, color=(255,0,0), thickness=2)
        debug_view(draw_contour, "Contours Fishing")
        draw_contour = cv2.drawContours(copy.deepcopy(img), contours_r, 0, color=(255,0,0), thickness=2)
        debug_view(draw_contour, "Contours NOT Fishing")

    # Creating a copy of image
    im2 = img.copy()
    im3 = img.copy()
    
    # Looping through the identified contours
    # Then rectangular part is cropped and passed on
    # to pytesseract for extracting text from it
    working = False
    not_working = False

    for cnt in contours_g:
        x, y, w, h = cv2.boundingRect(cnt)
        # Cropping the text block for giving input to OCR
        cropped = im2[y:y + h, x:x + w]
        text = pytesseract.image_to_string(cropped)
        working = True

        if DEBUG:
            # Drawing a rectangle on copied image
            rect = cv2.rectangle(im2, (x, y), (x + w, y + h), (0, 255, 0), 2)
            print('(GREEN) WE ARE: %s'%(text))
            debug_view(rect)

    for cnt in contours_r:
        x, y, w, h = cv2.boundingRect(cnt)
        # Cropping the text block for giving input to OCR
        cropped = im3[y:y + h, x:x + w]
        text = pytesseract.image_to_string(cropped)
        not_working = True

        if DEBUG:
            # Drawing a rectangle on copied image
            rect = cv2.rectangle(im3, (x, y), (x + w, y + h), (0, 255, 0), 2)
            print('(RED) WE ARE: %s'%(text))
            debug_view(rect)

    # 2 means there is no action text, or it failed to find anything, this distinction might not be necessary
    result = 2
    if working:
        result = 0
    elif not_working:
        result = 1
    return result
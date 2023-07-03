#imports
import numpy as np
import math
import time
import cv2
import bot_env as screen
import copy
import pytesseract


# This class handles object recognition and the images required for the rest of the bot to function
class BotEyes():
    def __init__(self, win_rect=[], DEBUG=False):
        # Relative path to the tesseract executable
        self.tesseract_path = r'..\\..\\Tesseract-OCR\\tesseract.exe'

        # Inventory location in a client screenshot -> easier for image recognition and future screenshots
        self.inventory_rect = None

        # Inventory location on monitor -> easier for click locations
        self.inventory_global = None

        # Image of current inventory -> easier for image recognition
        self.curr_inventory = None

        # Client rect -> pass from BotBrain object
        self.client_rect = win_rect

        # Image of client
        self.curr_client = None

        # Center of the client
        self.local_center = None
        self.global_center = None

        # Debug flag
        self._DEBUG=DEBUG


    # Force debugging at any point
    def force_debug(self, DEBUG=False):
        self._DEBUG=DEBUG


    # Update the rect and associated values
    def setRect(self, new_rect):
        self.client_rect = new_rect
        self.find_center()
        self.find_inventory()
        self.grab_inventory()
        self.check_inventory()
        

    # Grab 
    def grab_inventory(self):
        image = copy.deepcopy(self.curr_client)
        try:
            if self.inventory_rect == []:
                self.find_inventory(image)
            # Need to account for the fact that the image typically sent to grab_inventory is of the client only
            if self._DEBUG:
                screen.debug_view(image, "Session Inventory")
                screenshot_check = screen.screen_image()
                screenshot_check = cv2.rectangle(screenshot_check, self.inventory_global, color=(0,255,0), thickness=2)
                screen.debug_view(screenshot_check, title='True inventory position')
            
        except:
            return False


    # Locate the inventory on the client screen and returns the corners
    def find_inventory(self, threshold=0.7):
        self.check_client()
        image = copy.deepcopy(self.curr_client)
        image_gray = cv2.cvtColor(copy.deepcopy(image), cv2.COLOR_BGR2GRAY)
        template = cv2.imread('images/ui_icons.png', 0)
        w, h = template.shape[::-1]
        pt = None
        res = cv2.matchTemplate(image_gray, template, cv2.TM_CCOEFF_NORMED)

        loc = np.where(res >= threshold)
        # print('LOC: ', len(loc))
        for pt in zip(*loc[::-1]):
            cv2.rectangle(image_gray, pt, (pt[0] + w, pt[1] + h), (0, 0, 255), 2)
            # cv2.circle(image, pt, radius=10, color=(255,0,0), thickness=2)
        try:
            #182x255
            self.inventory_rect = [pt[0]+20, pt[1]+35, 182, 255]
            self.inventory_global = [self.inventory_rect[0] + self.client_rect[0], self.inventory_rect[1] + self.client_rect[1], self.inventory_rect[2], self.inventory_rect[3]]
            if self._DEBUG:
                cv2.rectangle(image, self.inventory_rect, (0, 0, 255), 2)
                print(self.inventory_rect)
                screen.debug_view(image_gray)
                screen.debug_view(image)
        except:
            return []
        

    # Updates the inventory image
    def check_inventory(self):
        self.curr_inventory = screen.screen_image(rect=self.inventory_global, DEBUG=self._DEBUG)


    # Updates the client image
    def check_client(self):
        self.curr_client = screen.block_name(screen.screen_image(rect=self.client_rect, DEBUG=self._DEBUG))
        

    # Block the inventory in the given image
    def update(self):
        # Cover the inventory, only call after init, assume it wont be called prior
        self.check_client()
        self.check_inventory()
        # Place a black rectangle covering the inventory
        self.curr_client = cv2.rectangle(self.curr_client, self.inventory_rect, color=(0, 0, 0), thickness=-1)


    # Locate the chat area on the client screen and returns the corners
    def find_chat(self, image, threshold=0.7):
        image_gray = cv2.cvtColor(screen.resize_image(image, scale_percent=70), cv2.COLOR_BGR2GRAY)
        template = cv2.imread('images/chat_template.png', 0)
        w, h = template.shape[::-1]
        pt = None
        res = cv2.matchTemplate(image_gray, template, cv2.TM_CCOEFF_NORMED)
        loc = np.where(res >= threshold)
        # There should be only one match
        for pt in zip(*loc[::-1]):
            rect = cv2.rectangle(image, pt, (pt[0] + w, pt[1] + h), (0, 0, 0), 2)
            cv2.circle(image, pt, radius=10, color=(255,0,0), thickness=2)
        x1, y1, x2, y2 = pt[0]+20, pt[1]+35, pt[0] + 200, pt[1] + 290
        if self._DEBUG:
            cv2.rectangle(image, (x1, y1), (x2, y2), (0, 0, 255), 2)
        return x1, y1, x2, y2


    # A function that sets the local and global centers. This can be used in other functions since the character is always semi-centered
    # Requires BotBrain to assign win_rect in init, otherwise just finds the global center of a rectangle
    def find_center(self):
        #self.client_rect is top-left (x, y) then width and height
        image_center = [math.floor(self.client_rect[2]/2), math.floor(self.client_rect[3]/2)]
        true_center = [image_center[0] + self.client_rect[0], image_center[1] + self.client_rect[1]]

        if self._DEBUG:
            print('IMAGE CENTER ', image_center)
            print('TRUE CENTER ', true_center)
            image = screen.screen_image(self.client_rect)
            image = cv2.circle(image, center=image_center, radius=10, color=(255, 100, 100), thickness=-1)
            screen.debug_view(image, title='IMAGE CENTER')
            image = screen.screen_image([0, 0, 1920, 1040])
            image = cv2.circle(image, center=true_center, radius=10, color=(100, 100, 255), thickness=-1)
            screen.debug_view(image, title='TRUE CENTER')

        self.local_center = image_center
        self.global_center = true_center


    # Locates and draws contours around colors defined by the boundaries param
    def locate_color(self, image, boundaries=[([180, 0, 180], [220, 20, 220])]):
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

        if self._DEBUG:
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

            if self._DEBUG:
                cv2.imwrite("images/Locate_Image_DebugPOST.png", image)
                print('Length of contours: %d'%(len(contours)))
                print(x, y, w, h)

            return [x_center, y_center]
        else:
            return []
        

    # Similar to using 'substring in string', but with images
    def locate_image(self, img_og, inv=False, filename='', threshold=0.8, name='Screenshot'):
        img_rgb = copy.deepcopy(img_og)
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
                if self._DEBUG:
                    cv2.rectangle(img_rgb, pt, (pt[0] + w, pt[1] + h), (255, 0, 0), thickness=1)
                if mask[pt[1] + int(round(h/2)), pt[0] + int(round(w/2))] != 255:
                    mask[pt[1]:pt[1]+h, pt[0]:pt[0]+w] = 255
                    # An array of points
                    items.append([pt[0] + math.floor(w/2) + (self.inventory_global[0] if inv else 0), pt[1] + math.floor(h/2) + (self.inventory_global[1] if inv else 0)])
                    if self._DEBUG:
                        cv2.circle(img_rgb, (pt[0]+math.floor(w/2), pt[1]+math.floor(h/2)), radius=min(math.floor(w/3), math.floor(h/3)), color=(0,255,0), thickness=1)
            if self._DEBUG:
                screen.debug_view(img_rgb, 'View image')
            if len(items) > 0:
                return items
            print('Locate image could not find the image ', filename)
            return []
        except:
            print('Locate image failed!')
            return []
        
        
    # Needs to be adjusted to find the action text and read it - not implemented
    def get_action_text(self, client_rect):
        scale = 300
        # I don't identify the locaiton of the fishing/mining/woodcutting text since I havent trained on the osrs font,
        # make sure it's dragged to the top-left area!
        screen.screen_image([client_rect[0]+25, client_rect[1]+50, 100, 30], 'Session_Action.png')
        img = screen.resize_image(cv2.imread('images/Session_Action.png'), scale)
        if self._DEBUG:
            screen.debug_view(img)

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
        if self._DEBUG:
            draw_contour = cv2.drawContours(copy.deepcopy(img), contours_g, 0, color=(255,0,0), thickness=2)
            screen.debug_view(draw_contour, "Contours Fishing")
            draw_contour = cv2.drawContours(copy.deepcopy(img), contours_r, 0, color=(255,0,0), thickness=2)
            screen.debug_view(draw_contour, "Contours NOT Fishing")

        # Creating a copy of image for text areas from red and green contours, helps with detection
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

            if self._DEBUG:
                # Drawing a rectangle on copied image
                rect = cv2.rectangle(im2, (x, y), (x + w, y + h), (0, 255, 0), 2)
                print('(GREEN) WE ARE: %s'%(text))
                screen.debug_view(rect)

        for cnt in contours_r:
            x, y, w, h = cv2.boundingRect(cnt)
            # Cropping the text block for giving input to OCR
            cropped = im3[y:y + h, x:x + w]
            text = pytesseract.image_to_string(cropped)
            not_working = True

            if self._DEBUG:
                # Drawing a rectangle on copied image
                rect = cv2.rectangle(im3, (x, y), (x + w, y + h), (0, 255, 0), 2)
                print('(RED) WE ARE: %s'%(text))
                screen.debug_view(rect)

        # 2 means there is no action text, or it failed to find anything, this distinction might not be necessary
        result = 2
        if working:
            result = 0
        elif not_working:
            result = 1
        return result
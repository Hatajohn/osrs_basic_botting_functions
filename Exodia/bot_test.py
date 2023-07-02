DEBUG = True
    bot = BotEyes(DEBUG)
    print('We are doing an action: ', get_action_text(bot, DEBUG) is 0)

    # print('Did I do it right? ', os.path.exists(tesseract_path))

    print('Get screenshot of window')
    # Some initial setup
    base_image = init_session(DEBUG=False)
    screenshot_check = screen.screen_image([0, 0, 1920, 1040])
    rect = get_window_rect(DEBUG=False)
    rect_w = get_window_rect(wrong=True)
    screenshot_check = cv2.rectangle(screenshot_check, rect, color=(0,255,0), thickness=3)
    screenshot_check = cv2.rectangle(screenshot_check, rect_w, color=(0,0,255), thickness=3)
    # debug_view(screenshot_check)
    screenshot_check = screen.screen_image(get_window_rect())
    # debug_view(screenshot_check)
    print(find_center(False))
    # cv2.imshow("First screenshot", np.hstack([image]))
    # cv2.waitKey(0)
    # find_center(image, DEBUG=True)

    # RGB color=(200,10,200) opacity 255
    # Arrays in boundaries are actually in B, G, R format

    # Colors
    # click_here([find_center()], image=copy.deepcopy(base_image))
    # time.sleep(0.6)
    # hit_escape()
    # time.sleep(0.6)
    # refresh_session()
    #click_info = locate_color(copy.deepcopy(globals()['client']), boundaries=[([216, 215, 0], [236, 235, 10])], DEBUG=True)

    # Fish
    # click_info = locate_image(image, r'Angler_Spot.png', name='Find Fishing Spots', DEBUG=True)
    # fishing_text_loc = locate_image(copy.deepcopy(base_image), r'Fishing_text.png', area='screen', name='Locate fishing text', DEBUG=DEBUG)
    # not_fishing_loc = locate_image(copy.deepcopy(base_image), r'Not_fishing_text.png', area='screen', name='Locate Not-fishing text', DEBUG=DEBUG)

    # while(not click_info):
    #    image = screen_image()
    #    # Scan for image

        # Get location for image
    DEBUG1 = False
    DEBUG2 = False
    # debug_view(base_image)
    click_info = locate_image(copy.deepcopy(base_image), r'infernal_eel_spot.png', name='Find Fishing Spots', DEBUG_1=DEBUG1, DEBUG_2=DEBUG2)
    print('I see %d eel spots'%(len(click_info)))
    #    attempt += 1
    #    print(attempt)
    # base_image = refresh_session()
    inv = cv2.imread('images/Session_Inventory.png')
    click_info = locate_image(copy.deepcopy(inv), r'infernal_eel_fish.png', name='Find Fish in Inv', DEBUG_1=DEBUG1, DEBUG_2=DEBUG2)
    if len(click_info) == 0:
        print('I have no eels')
    else:
        print('I have %d eels'%(len(click_info)))
    click_info = locate_image(copy.deepcopy(inv), r'imcando_hammer.png', name='Find Imcando Hammer in Inv', DEBUG_1=DEBUG1, DEBUG_2=DEBUG2)
    print('I have %d hammer'%(len(click_info)))

    print('We are doing an action: ', get_action_text() is 0)

    # Drag middle mouse from near-center to a random poing
    rand = [random.randrange(-200,200), random.randrange(-200,200)]
    # control_camera(pick_point_in_circle(rand, rad=100))

    # Find Yellow
    # click_info = locate_color(base_image, boundaries=[([0, 245, 245], [10, 255, 255])], DEBUG=True)
    # print(click_info)
    # click_here(click_info, image, DEBUG=DEBUG)
    # click_logout(DEBUG=True)
    # click_logout(FAST=True)

    click_info = locate_image(copy.deepcopy(inv), r'knife.png', name='Find Magic Trees', DEBUG_1=DEBUG1, DEBUG_2=DEBUG2)
    if len(click_info) == 0:
        print('I don\'t have a knife')
    else:
        print('I see %d knives'%(len(click_info)))
    click_info = locate_image(copy.deepcopy(inv), r'magic_logs.png', name='Find magic logs in inv', DEBUG_1=DEBUG1, DEBUG_2=DEBUG2)
    if len(click_info) == 0:
        print('I have no logs')
    else:
        print('I have %d logs'%(len(click_info)))

    if False:
        pan_left()
        time.sleep(1)
        pan_right()
        time.sleep(1)
        pan_up()
        time.sleep(1)
        pan_down()
        time.sleep(1)

        point = find_center()
        rect = get_window_rect()
        point = [point[0] - math.floor(rect[2]/2 * 0.90), point[1] - math.floor(rect[3]/2 * 0.90)]
        pan_to(point=point)
    
    # find_inventory(image, DEBUG=True)
    # find_chat(image, DEBUG=True)
    # Click on a fishing spot
            
    # image = isolate_playspace(image)
    # image = isolate_inventory(image)
    # image = resize_image(image, 75)0

    # cv2.imshow("Screenshot", np.hstack([resize_image(base_image, 50)]))
    # cv2.waitKey(0)
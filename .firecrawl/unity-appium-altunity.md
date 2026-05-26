- [Programming](https://www.gamedeveloper.com/programming)
- [Commentary](https://www.gamedeveloper.com/latest-commentary)

# How to: Automated Tests for Unity Mobile Apps with Appium and AltUnity

Tutorial article on how to automate tests for Unity mobile apps with Appium and AltUnity tools. It contains an example python project with the setup and steps needed to run a basic test scenario.

[![Picture of Timea Pusok](https://eu-images.contentstack.com/v3/assets/blt740a130ae3c5d529/blt178903e53133f84a/65088b0db185306592e2346e/Timea_Pusok.jpg?width=100&auto=webp&quality=80&disable=upscale)](https://www.gamedeveloper.com/author/timea-pusok)

[Timea Pusok,](https://www.gamedeveloper.com/author/timea-pusok) Blogger

April 22, 2021

3 Min Read

![Game Developer logo in a gray background | Game Developer](https://eu-images.contentstack.com/v3/assets/blt740a130ae3c5d529/bltba62518415cda0e2/652fe6ddbc479f8697ef691f/default-cubic.png?width=1280&auto=webp&quality=80&format=jpg&disable=upscale)

[Linkedin](https://www.linkedin.com/sharing/share-offsite/?url=https://www.gamedeveloper.com/programming/how-to-automated-tests-for-unity-mobile-apps-with-appium-and-altunity)[Facebook](http://www.facebook.com/sharer/sharer.php?u=https://www.gamedeveloper.com/programming/how-to-automated-tests-for-unity-mobile-apps-with-appium-and-altunity)[Twitter](http://www.twitter.com/intent/tweet?url=https://www.gamedeveloper.com/programming/how-to-automated-tests-for-unity-mobile-apps-with-appium-and-altunity)[Reddit](https://www.reddit.com/submit?url=https://www.gamedeveloper.com/programming/how-to-automated-tests-for-unity-mobile-apps-with-appium-and-altunity&title=How%20to%3A%20Automated%20Tests%20for%20Unity%20Mobile%20Apps%20with%20Appium%20and%20AltUnity)[Bluesky](https://bsky.app/intent/compose?text=How%20to%3A%20Automated%20Tests%20for%20Unity%20Mobile%20Apps%20with%20Appium%20and%20AltUnity%20-%20https%3A%2F%2Fwww.gamedeveloper.com%2Fprogramming%2Fhow-to-automated-tests-for-unity-mobile-apps-with-appium-and-altunity)[Email](mailto:?subject=How%20to:%20Automated%20Tests%20for%20Unity%20Mobile%20Apps%20with%20Appium%20and%20AltUnity&body=I%20thought%20the%20following%20from%20Game%20Developer%20might%20interest%20you.%0D%0A%0D%0A%20How%20to%3A%20Automated%20Tests%20for%20Unity%20Mobile%20Apps%20with%20Appium%20and%20AltUnity%0D%0Ahttps%3A%2F%2Fwww.gamedeveloper.com%2Fprogramming%2Fhow-to-automated-tests-for-unity-mobile-apps-with-appium-and-altunity)

When it comes to mobile automation testing, there are many different choices for a tool. One popular option is [Appium](http://appium.io/), an open-source framework which enables running automated tests on both Android and iOS devices.

Although a powerful tool, Appium has some limitations related to interacting with some non-native application types, one example being Unity games. For this reason we use [AltUnity Tools](https://altom.com/testing-tools/altunitytester/), consisting of:

- [AltUnity Tester](https://assetstore.unity.com/packages/tools/utilities/altunity-tester-ui-test-automation-112101), an open source asset allowing you to identify and interact with Unity objects and run end-to-end automated tests on real devices

- [AltUnity Inspector](https://altom.com/testing-tools/altunitytester/#pricing), a desktop application helping you to visualize the game object hierarchy and get components, properties, methods and fields easily without access to the source code


## Why use Appium together with AltUnity Tools

There are a couple of scenarios for which you would want to use both of these frameworks at the same time:

- By itself, AltUnity Tester cannot launch an app on a device. If you want to run tests in a pipeline, or by using [cloud services](https://altom.gitlab.io/altunity/altunitytester/pages/tester-with-cloud.html#running-tests-using-device-cloud-services), you can either create a script which will start your app, or you can use Appium before the test execution;

- AltUnity Tester cannot perform some types of actions, such as interacting with any native popups your app might have, or putting the app in the background and resuming it. In any of these cases, you can use Appium to do the things that AltUnity Tester can’t.

- With AltUnity Inspector you can’t visualize the native objects. For this you could use the Appium Inspector.


## AltUnity Tester with Appium example

To help you get started on Unity test automation, we’ve created an example python project which can be found [here](https://gitlab.com/altom/altunity/examples/alttrashcat-tests-python-appium).

After you cloned it, there are a couple of things you need to check before running the tests:

- For Android you need to have Android SDK version 16 or higher installed on your machine;

- For iOS you need XCode with Command Line Tools installed (will only work on Mac OSX);

- Your mobile device needs to have developer mode enabled and be connected via USB to the machine running the tests.


### Inspecting the games

When writing the tests you’ll need information about the Unity objects. With AltUnity Inspector you can get objects’s paths, components, methods, fields and properties.

![](https://eu-images.contentstack.com/v3/assets/blt740a130ae3c5d529/blt90182456e2d76b5d/650ead823d5047703af8d185/AltUNityInspector2.png/?width=1280&auto=webp&quality=80&disable=upscale)

If your game contains native elements, you’ll need to use the Appium Inspector from which you can get the selectors and attributes.

![](https://eu-images.contentstack.com/v3/assets/blt740a130ae3c5d529/bltdb97fca61df5925a/650ead5da9a5e736938f7855/AppiumInspector2.png/?width=1280&auto=webp&quality=80&disable=upscale)

### Running the tests

- For Android, you can just run the script run-tests\_android.sh

- For iOS, you first need to export IOS\_UDID=<your-device-udid> then run the script run-tests\_ios.sh





  - To find out an iOS device UDID you can go to Finder, click the device in the sidebar and click the info under the device name to reveal the UDID


The script will install any requirements that are missing from your machine (except Android SDK and XCode CLT), then run a basic test scenario:

1. The app will be started by Appium;

2. AltUnity Tester will ensure it’s initially loaded;

3. Appium will put the app in the background for a couple of seconds, then resume it;

4. Appium will check if the app was resumed successfully.


Please observe the following about the setup method in base\_test.py:

1. A minimum amount of desired capabilities have to be set in order for Appium to work. More details about desired capabilities can be found in the official [Appium documentation](http://appium.io/docs/en/writing-running-appium/caps/index.html)

2. The Appium driver needs to be created before the port forwarding needed by AltUnity Tester is done. This is because Appium clears any other port forwarding when it starts.


Let us know if you tried our example and if you found it helpful. If you have any questions or feedback, please leave us a comment below or join us on [Discord](https://discord.com/invite/Ag9RSuS).

Read more about:

[Blogs](https://www.gamedeveloper.com/keyword/blogs)

[Linkedin](https://www.linkedin.com/sharing/share-offsite/?url=https://www.gamedeveloper.com/programming/how-to-automated-tests-for-unity-mobile-apps-with-appium-and-altunity)[Facebook](http://www.facebook.com/sharer/sharer.php?u=https://www.gamedeveloper.com/programming/how-to-automated-tests-for-unity-mobile-apps-with-appium-and-altunity)[Twitter](http://www.twitter.com/intent/tweet?url=https://www.gamedeveloper.com/programming/how-to-automated-tests-for-unity-mobile-apps-with-appium-and-altunity)[Reddit](https://www.reddit.com/submit?url=https://www.gamedeveloper.com/programming/how-to-automated-tests-for-unity-mobile-apps-with-appium-and-altunity&title=How%20to%3A%20Automated%20Tests%20for%20Unity%20Mobile%20Apps%20with%20Appium%20and%20AltUnity)[Bluesky](https://bsky.app/intent/compose?text=How%20to%3A%20Automated%20Tests%20for%20Unity%20Mobile%20Apps%20with%20Appium%20and%20AltUnity%20-%20https%3A%2F%2Fwww.gamedeveloper.com%2Fprogramming%2Fhow-to-automated-tests-for-unity-mobile-apps-with-appium-and-altunity)[Email](mailto:?subject=How%20to:%20Automated%20Tests%20for%20Unity%20Mobile%20Apps%20with%20Appium%20and%20AltUnity&body=I%20thought%20the%20following%20from%20Game%20Developer%20might%20interest%20you.%0D%0A%0D%0A%20How%20to%3A%20Automated%20Tests%20for%20Unity%20Mobile%20Apps%20with%20Appium%20and%20AltUnity%0D%0Ahttps%3A%2F%2Fwww.gamedeveloper.com%2Fprogramming%2Fhow-to-automated-tests-for-unity-mobile-apps-with-appium-and-altunity)

## About the Author

[![Timea Pusok](https://eu-images.contentstack.com/v3/assets/blt740a130ae3c5d529/blt178903e53133f84a/65088b0db185306592e2346e/Timea_Pusok.jpg?width=400&auto=webp&quality=80&disable=upscale)](https://www.gamedeveloper.com/author/timea-pusok)

[Timea Pusok](https://www.gamedeveloper.com/author/timea-pusok)

Blogger

[See more from Timea Pusok](https://www.gamedeveloper.com/author/timea-pusok)

Daily news, dev blogs, and stories from Game Developer straight to your inbox

[Stay Updated](https://gd-resources.gamedeveloper.com/free/w_gamf01/prgm.cgi)

### You May Also Like

[Programming![1000xResist creator: the game industry needs a universal video codec for FMV games](https://eu-images.contentstack.com/v3/assets/blt740a130ae3c5d529/blt129f7dc62469f7fd/69d6b6fa5ed3f47c70199152/proveyourhumanfeatured.jpg?width=1280&auto=webp&quality=80&disable=upscale)\\
\\
**1000xResist creator: the game industry needs a universal video codec for FMV games** \\
\\
by Bryant Francis\\
\\
Apr 09, 2026](https://www.gamedeveloper.com/programming/1000xresist-creator-the-game-industry-needs-a-universal-codec-for-fmv-games?recipe=related-items&source_content_id=18dbcf75be2ee0027ee48f5c20b52fab) [Programming![Clair Obscur: Expedition 33 was built '95 percent' with Unreal Engine Blueprints](https://eu-images.contentstack.com/v3/assets/blt740a130ae3c5d529/blte9b1c0681db0ff4f/69b0fa5820d92f61160f2e12/ss_8439c07d7b1f2fcfc6449db5f051f8d0867f4785.1920x1080.jpg?width=1280&auto=webp&quality=80&disable=upscale)\\
\\
**Clair Obscur: Expedition 33 was built '95 percent' with Unreal Engine Blueprints** \\
\\
by Bryant Francis\\
\\
Mar 11, 2026](https://www.gamedeveloper.com/programming/clair-obscur-expedition-33-was-built-95-percent-with-unreal-blueprints?recipe=related-items&source_content_id=9908815e155cc5a110bfaafcc106ea9b) [Programming![Unity says its AI tech will soon be able to 'prompt full casual games into existence' ](https://eu-images.contentstack.com/v3/assets/blt740a130ae3c5d529/blt416000ed89b80720/69934f2aeac83e0008690b71/Unity_AI_Header.png?width=1280&auto=webp&quality=80&disable=upscale)\\
\\
**Unity says its AI tech will soon be able to 'prompt full casual games into existence'** \\
\\
by Chris Kerr\\
\\
Feb 16, 2026](https://www.gamedeveloper.com/programming/unity-says-its-ai-tech-will-soon-be-able-to-prompt-full-casual-games-into-existence-?recipe=related-items&source_content_id=79cc713b67698760ebfa12cc7327a3db) [Programming![Godot 4.5 ushers in accessibility features, including screen reader support](https://eu-images.contentstack.com/v3/assets/blt740a130ae3c5d529/blte91aad09ff6b9f8d/68c97392119dea5dcdb4bf43/godot_logo.jpg?width=1280&auto=webp&quality=80&disable=upscale)\\
\\
**Godot 4.5 ushers in accessibility features, including screen reader support** \\
\\
by Diego Argüello\\
\\
Sep 16, 2025](https://www.gamedeveloper.com/programming/godot-4-5-ushers-in-accessibility-features-including-screen-reader-support?recipe=related-items&source_content_id=87758c6e7c3c3e398d8fc975e08ba547)

### Latest News

[More News](https://www.gamedeveloper.com/latest-news)

[![A screenshot of three players exploring the shallows in Subnautica 2 ](https://eu-images.contentstack.com/v3/assets/blt740a130ae3c5d529/blt3a82a3afcc704fe3/6a07070f0fe33240517b7496/Sub_2_Header.png?width=1280&auto=webp&quality=80&disable=upscale)](https://www.gamedeveloper.com/business/subnautica-2-has-surpassed-2-million-sales-in-12-hours)[Business](https://www.gamedeveloper.com/business)

[Subnautica 2 has surpassed 2 million sales in 12 hours](https://www.gamedeveloper.com/business/subnautica-2-has-surpassed-2-million-sales-in-12-hours) [Subnautica 2 has surpassed 2 million sales in 12 hours](https://www.gamedeveloper.com/business/subnautica-2-has-surpassed-2-million-sales-in-12-hours)

by [Chris Kerr](https://www.gamedeveloper.com/author/chris-kerr)

May 15, 2026

2 Min Read

[![The Patch Notes logo overlaid on key artwork for Grand Theft Auto VI](https://eu-images.contentstack.com/v3/assets/blt740a130ae3c5d529/blt8e865708f41a7e64/6a06f8ac38400214fd815eec/Patch_Notes_52_Header.png?width=1280&auto=webp&quality=80&disable=upscale)](https://www.gamedeveloper.com/business/politicians-accuse-rockstar-of-obstructing-legal-process-ebay-rebuffs-gamestop-and-video-game-hardware-screams-now-patch-notes-52)[Business](https://www.gamedeveloper.com/business)

[Politicians accuse Rockstar of obstructing legal process, eBay rebuffs GameStop, and video game hardware screams now - Patch Notes #52](https://www.gamedeveloper.com/business/politicians-accuse-rockstar-of-obstructing-legal-process-ebay-rebuffs-gamestop-and-video-game-hardware-screams-now-patch-notes-52) [Politicians accuse Rockstar of obstructing legal process, eBay rebuffs GameStop, and video game hardware screams now - Patch Notes #52](https://www.gamedeveloper.com/business/politicians-accuse-rockstar-of-obstructing-legal-process-ebay-rebuffs-gamestop-and-video-game-hardware-screams-now-patch-notes-52)

by [Chris Kerr](https://www.gamedeveloper.com/author/chris-kerr)

May 15, 2026

4 Min Read

Keep up with the latest News, Interviews, and Talk Coverage from GDC Festival of Gaming right here on Game Developer

[READ ON](https://www.gamedeveloper.com/keyword/gdc-festival-of-gaming)

Latest Podcasts

- [Production](https://www.gamedeveloper.com/production) [Stories from making Marvel Rivals](https://www.gamedeveloper.com/production/stories-from-making-marvel-rivals) May 15, 2026
- [PC](https://www.gamedeveloper.com/game-platforms/pc) [We tested the Steam Controller](https://www.gamedeveloper.com/pc/we-tested-the-steam-controller) May 1, 2026
- [Design](https://www.gamedeveloper.com/design) [Supporting juniors and sharpening your creativity](https://www.gamedeveloper.com/design/supporting-juniors-and-sharpening-your-creativity) Apr 17, 2026
- [Design](https://www.gamedeveloper.com/design) [Laptop mishaps and a GDC chat with Owlchemy Labs CEO Andrew Eiche](https://www.gamedeveloper.com/design/laptop-mishaps-and-a-gdc-chat-with-owlchemy-labs-ceo-andrew-eiche) Apr 3, 2026

[See all](https://www.gamedeveloper.com/keyword/game-developer-podcast)

### Game Developer Collective

[More](https://www.gamedeveloper.com/keyword/game-developer-collective)

[![A player character runs around with their arms extended in Rematch, other players stand behind them.](https://eu-images.contentstack.com/v3/assets/blt740a130ae3c5d529/blt7a79424246931087/6967e30f40bb4580b53d61e0/rematchfeatured.png?width=1280&auto=webp&quality=80&disable=upscale)](https://www.gamedeveloper.com/business/games-that-sell-dlc-and-in-app-purchases-appear-to-benefit-most-from-subscription-services)[Business](https://www.gamedeveloper.com/business)

[Games that sell DLC and in-app purchases appear to benefit most from subscription services](https://www.gamedeveloper.com/business/games-that-sell-dlc-and-in-app-purchases-appear-to-benefit-most-from-subscription-services) [Games that sell DLC and in-app purchases appear to benefit most from subscription services](https://www.gamedeveloper.com/business/games-that-sell-dlc-and-in-app-purchases-appear-to-benefit-most-from-subscription-services)

by [Bryant Francis](https://www.gamedeveloper.com/author/bryant-francis)

Jan 27, 2026

3 Min Read

[![An African American woman looks at a laptop in frustration.](https://eu-images.contentstack.com/v3/assets/blt740a130ae3c5d529/bltc5a3580ea6a37cdc/689b76d8b5ca625122beeab9/frustrateddeveloperfeatured.jpg?width=1280&auto=webp&quality=80&disable=upscale)](https://www.gamedeveloper.com/business/devs-are-more-worried-than-ever-that-generative-ai-will-lower-the-quality-of-games)[Business](https://www.gamedeveloper.com/business)

[Devs are more worried than ever that generative AI will lower the quality of games](https://www.gamedeveloper.com/business/devs-are-more-worried-than-ever-that-generative-ai-will-lower-the-quality-of-games) [Devs are more worried than ever that generative AI will lower the quality of games](https://www.gamedeveloper.com/business/devs-are-more-worried-than-ever-that-generative-ai-will-lower-the-quality-of-games)

by [Bryant Francis](https://www.gamedeveloper.com/author/bryant-francis)

Sep 16, 2025

4 Min Read

[![A man in a suit hides his face as eight hands point at him in blame.](https://eu-images.contentstack.com/v3/assets/blt740a130ae3c5d529/blt6f01525d72f5b1c3/687669d83f53364453f30bf2/blameinvestorsfeatured.jpg?width=1280&auto=webp&quality=80&disable=upscale)](https://www.gamedeveloper.com/business/are-unreasonable-investor-expectations-the-cause-of-poor-video-game-market-conditions-)[Business](https://www.gamedeveloper.com/business)

[Are 'unreasonable investor expectations' the cause of poor video game market conditions?](https://www.gamedeveloper.com/business/are-unreasonable-investor-expectations-the-cause-of-poor-video-game-market-conditions-) [Are 'unreasonable investor expectations' the cause of poor video game market conditions?](https://www.gamedeveloper.com/business/are-unreasonable-investor-expectations-the-cause-of-poor-video-game-market-conditions-)

by [Bryant Francis](https://www.gamedeveloper.com/author/bryant-francis)

Jul 15, 2025

5 Min Read

### Game Design & Marketing Highlights

[See More](https://www.gamedeveloper.com/marketing)

[![Iron Man, Storm, Loki, and Luna Snow in key art for Marvel Rivals, next to the Game Developer Podcast logo.](https://eu-images.contentstack.com/v3/assets/blt740a130ae3c5d529/bltbc75f0b553cd3045/6a0627668388ef32b7945f5f/marvelrivalsgdc.png?width=1280&auto=webp&quality=80&disable=upscale)](https://www.gamedeveloper.com/production/stories-from-making-marvel-rivals)[Production](https://www.gamedeveloper.com/production)  [Link to all podcast](https://www.gamedeveloper.com/production/stories-from-making-marvel-rivals "Link to all podcast")

[Stories from making Marvel Rivals](https://www.gamedeveloper.com/production/stories-from-making-marvel-rivals) [Stories from making Marvel Rivals](https://www.gamedeveloper.com/production/stories-from-making-marvel-rivals)

[![The Triple-i Initiative logo. ](https://eu-images.contentstack.com/v3/assets/blt740a130ae3c5d529/bltacf5f37dee2e79a7/69fc90c6074d2dd9b62242b5/tripleibenfeatured.jpg?width=1280&auto=webp&quality=80&disable=upscale)](https://www.gamedeveloper.com/marketing/-not-for-profit-biz-models-can-make-for-better-showcases-say-triple-i-initiative-organizers)[Marketing](https://www.gamedeveloper.com/marketing)

['Not-for-profit' biz models can make for better showcases, say Triple-i Initiative organizers](https://www.gamedeveloper.com/marketing/-not-for-profit-biz-models-can-make-for-better-showcases-say-triple-i-initiative-organizers) ['Not-for-profit' biz models can make for better showcases, say Triple-i Initiative organizers](https://www.gamedeveloper.com/marketing/-not-for-profit-biz-models-can-make-for-better-showcases-say-triple-i-initiative-organizers)

[![Characters create epic food in Dosa Divas](https://eu-images.contentstack.com/v3/assets/blt740a130ae3c5d529/blt36fbe130dc5ee559/69f8d1ced433801659958350/dosa_divas_action_shot.jpg?width=1280&auto=webp&quality=80&disable=upscale)](https://www.gamedeveloper.com/business/meet-the-indie-studios-funding-other-indie-studios)[Business](https://www.gamedeveloper.com/business)

[Meet the indie studios funding other indie studios](https://www.gamedeveloper.com/business/meet-the-indie-studios-funding-other-indie-studios) [Meet the indie studios funding other indie studios](https://www.gamedeveloper.com/business/meet-the-indie-studios-funding-other-indie-studios)

[![A photo of the Steam Controller by the Game Developer Podcast logo.](https://eu-images.contentstack.com/v3/assets/blt740a130ae3c5d529/blt7faa05950769285e/69ef7df24b4c9e032fd51633/SteamController.png?width=1280&auto=webp&quality=80&disable=upscale)](https://www.gamedeveloper.com/pc/we-tested-the-steam-controller)[PC](https://www.gamedeveloper.com/game-platforms/pc)  [Link to all podcast](https://www.gamedeveloper.com/pc/we-tested-the-steam-controller "Link to all podcast")

[We tested the Steam Controller](https://www.gamedeveloper.com/pc/we-tested-the-steam-controller) [We tested the Steam Controller](https://www.gamedeveloper.com/pc/we-tested-the-steam-controller)
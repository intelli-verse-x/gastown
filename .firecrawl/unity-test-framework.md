![Hero background image](https://unity.com/_next/image?url=https%3A%2F%2Fcdn.sanity.io%2Fimages%2Ffuvbjjlp%2Fproduction%2Faa6d5d01cdf46477b0382a8b708b85146914e389-810x528.jpg&w=3840&q=75)

# How to run automated tests for your games with the Unity Test Framework

In game development, manual testing can quickly become repetitive and prone to error. Have you ever found yourself in one of these seemingly endless testing cycles as you work on a new feature or try to fix a bug?

By automating your code testing, you can spend more time on creative game development and less on repetitive (but important) QA tasks which ensure that adding, removing, or changing code does not break your project.

Unity helps you create, manage, and run automated tests for your games with the [Unity Test Framework](https://web.archive.org/web/20240415020832/https://docs.unity3d.com/Packages/com.unity.test-framework@1.3/manual/course/welcome.html).

### Test two ways in Unity Test Framework

Unity Test Framework (UTF) allows you to test your project code in both **Edit** and **Play** modes. You can also target test code for various platforms such as standalone, iOS, or Android.

The UTF is installed by adding it to your project with the **Package Manager**.

Under the hood, UTF integrates with [NUnit](https://web.archive.org/web/20240415020832/http://www.nunit.org/), which is a well-known open source testing library for .NET languages.

There are two main categories of tests you can write with UTF, Edit mode and Play mode:

**Edit mode** tests run in the Unity Editor and have access to both Editor and game code. This means you can test your custom Editor extensions or use tests to modify settings in the Editor and enter Play mode, which is useful for adjusting Inspector values and then running automated tests with many different settings.

**Play mode** tests let you exercise your game code at runtime. Tests are generally run as [coroutines](https://web.archive.org/web/20240415020832/https://docs.unity3d.com/ScriptReference/Coroutine.html) using the **\[UnityTest\]** attribute. This allows you to test code that can run across multiple frames. By default, Play mode tests will run in the Editor, but you can also run them in a standalone player build for various target platforms.

![automated tests](https://unity.com/_next/image?url=https%3A%2F%2Fcdn.sanity.io%2Fimages%2Ffuvbjjlp%2Fproduction%2Fd181392bed34f5248c3ca059eaf83569b62b4f84-810x312.jpg&w=3840&q=75)

The Third Person Character Controller package, available in the Unity Asset Store

### How to test Unity Test Framework

To follow along with this example, you’ll need to install the [Starter Assets – Third Person Character Controller package](https://web.archive.org/web/20240415020832/https://assetstore.unity.com/packages/essentials/starter-assets-third-person-character-controller-196526) from the Unity Asset Store and import it into a new project.

![automated tests](https://unity.com/_next/image?url=https%3A%2F%2Fcdn.sanity.io%2Fimages%2Ffuvbjjlp%2Fproduction%2F725862d447fcdc123a9cbee98da0dc98eee59992-810x287.jpg&w=3840&q=75)

The manifest.json file

### Setting up Unity Test Framework

Install UTF via **Window > Package Manager**. Search for Test Framework under the Unity Registry in the Package Manager. Make sure to select version 1.3.3 (the latest version at time of writing).

Once UTF is installed, open the Packages/manifest.json file with a text editor, and add a testables section after dependencies, like this:

**,**

**"testables": \[**\
\
**"com.unity.inputsystem"**\
\
**\]**

Save the file. This will be useful later on, when you’ll need to reference the Unity.InputSystem.TestFramework assembly for testing and emulating player input.

Return to the Editor and allow the newer version to install.

![automated tests](https://unity.com/_next/image?url=https%3A%2F%2Fcdn.sanity.io%2Fimages%2Ffuvbjjlp%2Fproduction%2F825e8a234f49e06b732cd08e078bfb7f5f9daa9a-810x653.jpg&w=3840&q=75)

Assembly Definition References in the Inspector for the Third Person Character Controller

### Test Assembly definitions

Click **Window > General > Test Runner** to view the **Test Runner** editor window.

In this part of the tutorial, the focus will be on creating Play mode tests. Rather than use the Create Test Assembly Folder options in the Test Runner Window, you’ll create them using the Project window.

With the root of your Project Assets folder highlighted, right-click and choose **Create > Testing > Tests Assembly Folder**.

A **Tests** project folder is added, containing a **Tests.asmdef** (assembly definition) file. This is required for tests to reference your game modules and dependencies.

The Character Controller code will be referenced in tests and will also need an assembly definition. Next, you’ll set up some assembly definitions and references to facilitate testing between the modules.

Right-click the **Assets/StarterAssets/InputSystem** project folder, and choose **Create > Assembly Definition**. Name it something descriptive, for example **StarterAssetsInputSystem**.

Select the new **StarterAssetsInputSystem.asmdef** file and, using the Inspector, add an Assembly Definition Reference to **Unity.InputSystem**. Click Apply.

Right-click the **Assets/StarterAssets/ThirdPersonController/Scripts** project folder, and choose **Create > Assembly Definition**. Name it something descriptive, for example **ThirdPersonControllerMain**.

As you did with the previous assembly definition, open ThirdPersonControllerMain in the Inspector and select references for:

\- Unity.InputSystem

\- StarterAssetsInputSystem

Click **Apply**.

![automated tests](https://unity.com/_next/image?url=https%3A%2F%2Fcdn.sanity.io%2Fimages%2Ffuvbjjlp%2Fproduction%2Ff70ee2240082f1c719135022f9afac303401e481-810x890.jpg&w=3840&q=75)

Adding references to assembly definitions

### Adding references to assembly definitions

To emulate parts of the Input System, you’ll need to reference it in your tests. Additionally, you’ll need to reference the StarterAssets namespace in an assembly that you’ll create for the Third Person Controller code.

Open **Tests.asmdef** in the Inspector and add a reference to the following assembly definitions:

\- UnityEngine.TestRunner

\- UnityEditor.TestRunner

\- Unity.InputSystem

\- Unity.InputSystem.TestFramework

\- ThirdPersonControllerMain

Click Apply.

![The Build Settings window](https://unity.com/_next/image?url=https%3A%2F%2Fcdn.sanity.io%2Fimages%2Ffuvbjjlp%2Fproduction%2F71213aa1179ada2e4574cd35d80da3ad46801aed-810x762.jpg&w=3840&q=75)

The Build Settings window

### Your first test

Your first test will cover some basics around loading and moving the main character from the Third Person Controller package.

Start off by setting up the new project with a simple test environment scene and a character Prefab resource to work with.

Open the scene named **Assets/StarterAssets/ThirdPersonController/Scenes/Playground.unity** and save a copy of it using the **File > Save As** menu to this new path: **Assets/Scenes/SimpleTesting.unity**

If you notice pink materials in the Game view, use the Render Pipeline Converter to upgrade materials from the Built-In Render Pipeline to the Universal Render Pipeline (URP). See [this article for a quick overview](https://web.archive.org/web/20240415020832/https://docs.unity3d.com/Packages/com.unity.render-pipelines.universal@12.1/manual/features/rp-converter.html).

Create a new folder in your Project Assets folder called **Resources**. Note: The folder name “Resources” is important here to allow for the Unity **Resources.Load()** method to be used.

Drag and drop the **PlayerArmature** GameObject in the Scene view into the new Resources folder, and choose to create an **Original Prefab** when prompted. Rename the Prefab asset **Character**.

This will be the base character Prefab used in your tests going forward.

Remove the PlayerArmature GameObject from the new **SimpleTesting** scene, and save the changes to the scene.

For the last step in the initial test setup, go to **File > Build Settings**, and choose Add Open Scenes to add the **Scenes/SimpleTesting** scene to the build settings.

### Create a C\# test script

Select the Tests folder in the Project Assets folder. Right-click and choose **Create** **>** **Testing** **>** **C# Test Script**.

Name the new Script **CharacterTests**. Open the script in your IDE to take a closer look.

Two method stubs are supplied with the initial class file, demonstrating some test basics.

Next, you’ll ensure tests load a “testing focused” game scene. This should be a scene containing the bare minimum required to test the system or component you’re focusing on.

Update the CharacterTests class to add two new **using** statements, and implement the **InputTestFixture** class:

**using UnityEngine.InputSystem;**

**using UnityEngine.SceneManagement;**

**public class CharacterTests : InputTestFixture**

Add two private fields to the top of the CharacterTests class:

**GameObject character = Resources.Load<GameObject>("Character");**

**Keyboard keyboard;**

The character field will store a reference to the Character Prefab, loaded from the Resources folder. **Keyboard** will hold a reference to the Keyboard input device provided by the InputSystem.

Override the base InputTestFixture class’ Setup() method by providing your own in the CharacterTests class:

**public override void Setup()**

**{**

**SceneManager.LoadScene("Scenes/SimpleTesting");**

**base.Setup();**

**keyboard = InputSystem.AddDevice<Keyboard>();**

**var mouse = InputSystem.AddDevice<Mouse>();**

**Press(mouse.rightButton);**

**Release(mouse.rightButton);;**

**}**

The Setup() method runs the base class Setup() method and then sets up your own CharacterTests class by loading the test scene and initializing the keyboard input device.

The mouse input is added purely for the Third Person Controller to begin to receive input from the simulated/virtual keyboard device. This is almost like a ‘set focus’ action.

For your first test, you’ll instantiate the character from the Prefab and assert that it is not null. Add the following method to your test class:

**\[Test\]**

**public void TestPlayerInstantiation()**

**{**

**GameObject characterInstance = GameObject.Instantiate(character, Vector3.zero, Quaternion.identity);**

**Assert.That(characterInstance, !Is.Null);**

**}**

While you’re there, you might want to clean up the sample template test methods. Remove the **CharacterTestsSimplePasses** and **CharacterTestsWithEnumeratorPasses** methods.

This file contains hidden or bidirectional Unicode text that may be interpreted or compiled differently than what appears below. To review, open the file in an editor that reveals hidden Unicode characters.
[Learn more about bidirectional Unicode characters](https://github.co/hiddenchars)

[Show hidden characters](https://unity.com/how-to/automated-tests-unity-test-framework)

|     |     |
| --- | --- |
|  | \[UnityTest\] |
|  | public IEnumerator TestPlayerMoves() |
|  | { |
|  | GameObject characterInstance = GameObject.Instantiate(character, Vector3.zero, Quaternion.identity); |
|  |  |
|  | Press(keyboard.upArrowKey); |
|  | yield return new WaitForSeconds(1f); |
|  | Release(keyboard.upArrowKey); |
|  | yield return new WaitForSeconds(1f); |
|  |  |
|  | Assert.That(characterInstance.transform.GetChild(0).transform.position.z, Is.GreaterThan(1.5f)); |
|  | } |

[view raw](https://gist.github.com/webcontent112233/a19edc4aef81cd7e64f435a4591f68ae/raw/141150f748200590b0c9c4c5516b4e07611db489/TestPlayerMoves) [TestPlayerMoves](https://gist.github.com/webcontent112233/a19edc4aef81cd7e64f435a4591f68ae#file-testplayermoves)
hosted with ❤ by [GitHub](https://github.com/)

![test passed check](https://unity.com/_next/image?url=https%3A%2F%2Fcdn.sanity.io%2Fimages%2Ffuvbjjlp%2Fproduction%2F66baa2aa84feaa081b157e39d084e0ef4f070693-810x241.jpg&w=3840&q=75)

The green checkmark signifies that the test has passed successfully

### Passing your first test

Save the script and head back to the **Test Runner** window in the Editor. Highlight the **TestPlayerInstantiation** test and click **Run Selected**.

The green checkmark signifies a passing test. You have asserted that the character can be loaded from resources, instantiated into the test scene, and is not null at that point.

You might have noticed that the **\[Test\]** annotation was used for this test instead of the **\[UnityTest\]** annotation. The UnityTest attribute allows coroutines to run tests over multiple frames. In this case, you just need to instantiate the character and assert that it was loaded.

Generally, you should use the NUnit Test attribute instead of the UnityTest attribute in Edit mode, unless you need to yield special instructions, need to skip a frame, or wait for a certain amount of time in Play mode.

![Testing character movement in Play mode](https://unity.com/_next/image?url=https%3A%2F%2Fcdn.sanity.io%2Fimages%2Ffuvbjjlp%2Fproduction%2F5b28d6cb266226b087ad6c2aad68727103e12e26-810x441.jpg&w=3840&q=75)

Testing character movement in Play mode

### Character movement tests

Next, you’ll use the UnityTest as you assert that holding down the forward controller key moves the character forward.

Add the new test method provided below to your CharacterTests class.

Two new test helper methods have appeared; Press() and Release(). These are both provided by the **InputTestFixture** base class and help you by emulating InputSystem control pressing and releasing.

The TestPlayerMoves() method does the following:

Instantiates an instance of the character from the character Prefab at location **(X: 0, Y: 0, Z: 0)**

Presses the up arrow key on the virtual keyboard for 1 second, then releases it

Waits 1 more second (for the character to slow down and stop moving)

Asserts that the character has moved to a position on the Z axis greater than 1.5 units.

Save the file, return to the Test Runner, and run the new test.

This file contains hidden or bidirectional Unicode text that may be interpreted or compiled differently than what appears below. To review, open the file in an editor that reveals hidden Unicode characters.
[Learn more about bidirectional Unicode characters](https://github.co/hiddenchars)

[Show hidden characters](https://unity.com/how-to/automated-tests-unity-test-framework)

|     |     |
| --- | --- |
|  | \[UnityTest\] |
|  | public IEnumerator TestPlayerMoves() |
|  | { |
|  | GameObject characterInstance = GameObject.Instantiate(character, Vector3.zero, Quaternion.identity); |
|  |  |
|  | Press(keyboard.upArrowKey); |
|  | yield return new WaitForSeconds(1f); |
|  | Release(keyboard.upArrowKey); |
|  | yield return new WaitForSeconds(1f); |
|  |  |
|  | Assert.That(characterInstance.transform.GetChild(0).transform.position.z, Is.GreaterThan(1.5f)); |
|  | } |

[view raw](https://gist.github.com/webcontent112233/a19edc4aef81cd7e64f435a4591f68ae/raw/141150f748200590b0c9c4c5516b4e07611db489/TestPlayerMoves) [TestPlayerMoves](https://gist.github.com/webcontent112233/a19edc4aef81cd7e64f435a4591f68ae#file-testplayermoves)
hosted with ❤ by [GitHub](https://github.com/)

![The Player Health script](https://unity.com/_next/image?url=https%3A%2F%2Fcdn.sanity.io%2Fimages%2Ffuvbjjlp%2Fproduction%2Fa731f35d0355d8608a2bf1ceafad644fa36a8031-810x681.jpg&w=3840&q=75)

The Player Health script

### Testing fall damage

Next, you’ll test a custom Monobehaviour script by adding a simple Player Health component.

Create a new script under **Assets/StarterAssets/ThirdPersonController/Scripts**. Name it **PlayerHealth**.

Open the script in your IDE and replace the contents with the code provided below.

There is a lot of new code added here. To summarize it, this script will determine if the player character is in a falling state. If the ground is hit once in a falling state, then the character’s health is reduced by 10%.

Locate the Character Prefab under **Assets/Resources**. Open the Prefab and add the new PlayerHealth script component.

Next, you’ll use the test scene to assert that the player’s health drops after falling off a ledge.

Using the \[UnityTest\] attribute, you can write a Play mode test that tests for fall damage. When falling for more than 0.2 seconds, the player should take 0.1f damage (the equivalent of 10% of the maximum health).

In the **SimpleTesting** scene, you’ll see a staircase leading up to a ledge. This is a test platform to spawn the character on top of and test the **PlayerHealth** script.

Open **CharacterTests.cs** again and add a new test method named TestPlayerFallDamage:

**\[UnityTest\]**

**public IEnumerator TestPlayerFallDamage()**

**{**

**_// spawn the character in a high enough area in the test scene_**

**GameObject characterInstance = GameObject.Instantiate(character, new Vector3(0f, 4f, 17.2f), Quaternion.identity);**

**_// Get a reference to the PlayerHealth component and assert currently at full health (1f)_**

**var characterHealth = characterInstance.GetComponent<PlayerHealth>();**

**Assert.That(characterHealth.Health, Is.EqualTo(1f));**

**_// Walk off the ledge and wait for the fall_**

**Press(keyboard.upArrowKey);**

**yield return new WaitForSeconds(0.5f);**

**Release(keyboard.upArrowKey);**

**yield return new WaitForSeconds(2f);**

**_// Assert that 1 health point was lost due to the fall damage_**

**Assert.That(characterHealth.Health, Is.EqualTo(0.9f));**

**}**

You will also need to add a **using** reference to the StarterAssets namespace at the very top of the class file:

**using StarterAssets;**

The test above follows a typical [arrange, act, assert (AAA) pattern](https://web.archive.org/web/20240415020832/https://docs.microsoft.com/en-us/visualstudio/test/unit-test-basics), commonly found in testing:

- The **Arrange** section of a unit test method initializes objects and sets the value of the data that is passed to the method under test.
- The **Act** section invokes the method under test with the arranged parameters. In this case, invoking the method under test is handled by a physics interaction when the player hits the ground after falling.

The **Assert** section verifies that the action of the method under test behaves as expected.

Next, you’ll test a custom Monobehaviour script by adding a simple Player Health component.

Create a new script under **Assets/StarterAssets/ThirdPersonController/Scripts**. Name it **PlayerHealth**.

Open the script in your IDE and replace the contents with the code provided below.

There is a lot of new code added here. To summarize it, this script will determine if the player character is in a falling state. If the ground is hit once in a falling state, then the character’s health is reduced by 10%.

Locate the Character Prefab under **Assets/Resources**. Open the Prefab and add the new PlayerHealth script component.

Next, you’ll use the test scene to assert that the player’s health drops after falling off a ledge.

Using the \[UnityTest\] attribute, you can write a Play mode test that tests for fall damage. When falling for more than 0.2 seconds, the player should take 0.1f damage (the equivalent of 10% of the maximum health).

In the **SimpleTesting** scene, you’ll see a staircase leading up to a ledge. This is a test platform to spawn the character on top of and test the **PlayerHealth** script.

Open **CharacterTests.cs** again and add a new test method named TestPlayerFallDamage:

**\[UnityTest\]**

**public IEnumerator TestPlayerFallDamage()**

**{**

**_// spawn the character in a high enough area in the test scene_**

**GameObject characterInstance = GameObject.Instantiate(character, new Vector3(0f, 4f, 17.2f), Quaternion.identity);**

**_// Get a reference to the PlayerHealth component and assert currently at full health (1f)_**

**var characterHealth = characterInstance.GetComponent<PlayerHealth>();**

**Assert.That(characterHealth.Health, Is.EqualTo(1f));**

**_// Walk off the ledge and wait for the fall_**

**Press(keyboard.upArrowKey);**

**yield return new WaitForSeconds(0.5f);**

**Release(keyboard.upArrowKey);**

**yield return new WaitForSeconds(2f);**

**_// Assert that 1 health point was lost due to the fall damage_**

**Assert.That(characterHealth.Health, Is.EqualTo(0.9f));**

**}**

You will also need to add a **using** reference to the StarterAssets namespace at the very top of the class file:

**using StarterAssets;**

The test above follows a typical [arrange, act, assert (AAA) pattern](https://web.archive.org/web/20240415020832/https://docs.microsoft.com/en-us/visualstudio/test/unit-test-basics), commonly found in testing:

The **Arrange** section of a unit test method initializes objects and sets the value of the data that is passed to the method under test.

The **Act** section invokes the method under test with the arranged parameters. In this case, invoking the method under test is handled by a physics interaction when the player hits the ground after falling.

The **Assert** section verifies that the action of the method under test behaves as expected.

This file contains hidden or bidirectional Unicode text that may be interpreted or compiled differently than what appears below. To review, open the file in an editor that reveals hidden Unicode characters.
[Learn more about bidirectional Unicode characters](https://github.co/hiddenchars)

[Show hidden characters](https://unity.com/how-to/automated-tests-unity-test-framework)

|     |     |
| --- | --- |
|  | using UnityEngine; |
|  |  |
|  | namespace StarterAssets |
|  | { |
|  | \[RequireComponent(typeof(CharacterController))\] |
|  | public class PlayerHealth : MonoBehaviour |
|  | { |
|  | \[Header("Player Health and Fall Damage Settings")\] |
|  | \[Range(0.1f, 1f)\] |
|  | \[Tooltip("Starting health for the character.")\] |
|  | public float StartingHealth = 1.0f; |
|  |  |
|  | \[Range(0.1f, 1f)\] |
|  | \[Space(3f)\] |
|  | \[Tooltip("Starting health for the character.")\] |
|  | public float FallDamageTimeThreshold = 0.2f; |
|  |  |
|  | // player |
|  | \[SerializeField\] |
|  | private float \_fallingThreshold; |
|  | private CharacterController \_controller; |
|  |  |
|  | \[SerializeField\] |
|  | private float \_currentHealth; |
|  | private bool \_isFalling; |
|  |  |
|  | public float Health |
|  | { |
|  | get { return \_currentHealth; } |
|  | set { \_currentHealth = value; } |
|  | } |
|  |  |
|  | private void Awake() |
|  | { |
|  | \_controller = GetComponent<CharacterController>(); |
|  | \_fallingThreshold = FallDamageTimeThreshold; |
|  | \_currentHealth = StartingHealth; |
|  | } |
|  |  |
|  | private void Update() |
|  | { |
|  | if (!\_controller.isGrounded) |
|  | { |
|  | \_fallingThreshold -= Time.deltaTime; |
|  | } |
|  | else |
|  | { |
|  | \_fallingThreshold = FallDamageTimeThreshold; |
|  | if (\_isFalling) |
|  | { |
|  | \_isFalling = false; |
|  | \_currentHealth -= 0.1f; |
|  | } |
|  | } |
|  | if (\_fallingThreshold <= 0f) |
|  | { |
|  | \_isFalling = true; |
|  | } |
|  | } |
|  | } |
|  | } |

[view raw](https://gist.github.com/webcontent112233/65d5382f4cce2e99a87c3ff387650230/raw/ce9e0802fa63fa1f0dffa589b666c23d24a20f68/PlayerHealth) [PlayerHealth](https://gist.github.com/webcontent112233/65d5382f4cce2e99a87c3ff387650230#file-playerhealth)
hosted with ❤ by [GitHub](https://github.com/)

![Test Runner - running tests](https://unity.com/_next/image?url=https%3A%2F%2Fcdn.sanity.io%2Fimages%2Ffuvbjjlp%2Fproduction%2F492f5addef60046580e369018a2e2316dc6c7a30-810x528.jpg&w=3840&q=75)

A test to ensure that a character falls in the game as intended, including incurring the correct amount of damage

### Running the new test

Back in the Editor, run the new test. Running in Play mode, you’ll see the character walk off the edge, fall (exceeding the 0.2 second threshold to categorize a fall), and take damage after hitting the ground.

Tests not only serve the purpose of testing that code changes do not break functionality, they can also serve as documentation or pointers to help developers think about other aspects of the game when tweaking settings.

![How to switch test to run in a standalone player build](https://unity.com/_next/image?url=https%3A%2F%2Fcdn.sanity.io%2Fimages%2Ffuvbjjlp%2Fproduction%2F832ac35098f73ab4de8862bfe13a16bd34ab0060-810x124.jpg&w=3840&q=75)

How to switch test to run in a standalone player build

### Running tests in the Standalone player

As mentioned earlier, running Play mode tests in the Test Runner by default runs them in Play mode using the Unity Editor. You can change them to run under a standalone player too.

Use the Run Location drop-down selection in the Test Runner window to switch tests to run in Standalone player builds.

### Automation and CI

Once you have started to build a suite of tests, the next step is to run them automatically after builds are complete. Automated unit and integration tests that run after build are useful for catching regressions or bugs as early as possible. They can also run as part of a [remote automated build system in the cloud](https://web.archive.org/web/20240415020832/https://blog.unity.com/engine-platform/introducing-unity-devops-for-game-development).

### Splitting build and run

Oftentimes you will want to capture test run results in a custom format so that results can be shared with a wider audience. In order to capture test results outside of the Unity Editor, you’ll need to split up the build and run processes.

Create a new script in your Tests project folder named **SetupPlaymodeTestPlayer**.

The SetupPlaymodeTestPlayer class will implement the ITestPlayerBuildModifier interface. You’ll use this to override and “hook” into the ModifyOptions method, which receives the build’s player options, and allows you to modify them.

**using System.IO;**

**using UnityEditor;**

**using UnityEditor.TestTools;**

**\[assembly: TestPlayerBuildModifier(typeof(SetupPlaymodeTestPlayer))\]**

**public class SetupPlaymodeTestPlayer : ITestPlayerBuildModifier**

**{**

**public BuildPlayerOptions ModifyOptions(BuildPlayerOptions playerOptions)**

**{**

**playerOptions.options &= ~(BuildOptions.AutoRunPlayer \| BuildOptions.ConnectToHost);**

**var buildLocation = Path.GetFullPath("TestPlayers");**

**var fileName = Path.GetFileName(playerOptions.locationPathName);**

**if (!string.IsNullOrEmpty(fileName))**

**buildLocation = Path.Combine(buildLocation, fileName);**

**playerOptions.locationPathName = buildLocation;**

**return playerOptions;**

**}**

**}**

This custom Player Build modifier script does the following when tests are run in Play mode (Run Location: On Player):

Disables auto-run for built players and skips the player option that tries to connect to the host it is running on

Changes the build path location to a dedicated path within the project ( **TestPlayers**)

With this complete, you can now expect builds to be located in the **TestPlayers** folder whenever they finish building. This now completes the build modifications and severs the link between build and run.

Next, you’ll implement result reporting. This will allow you to write test results out to a custom location, ready for automated report generation and publishing.

Create a new script in your Tests project folder named **ResultSerializer** (provided below). This class will use an assembly reference to TestRunCallback and implement the ITestRunCallback interface.

This implementation of ITestRunCallback includes a customized RunFinished method, which is what sets up a player build with tests to write out the test results to an XML file named **testresults.xml**.

This file contains hidden or bidirectional Unicode text that may be interpreted or compiled differently than what appears below. To review, open the file in an editor that reveals hidden Unicode characters.
[Learn more about bidirectional Unicode characters](https://github.co/hiddenchars)

[Show hidden characters](https://unity.com/how-to/automated-tests-unity-test-framework)

|     |     |
| --- | --- |
|  | using NUnit.Framework.Interfaces; |
|  | using System.IO; |
|  | using System.Xml; |
|  | using UnityEngine; |
|  | using UnityEngine.TestRunner; |
|  |  |
|  | \[assembly:TestRunCallback(typeof(ResultSerializer))\] |
|  | public class ResultSerializer : ITestRunCallback |
|  | { |
|  | public void RunStarted(ITest testsToRun) { } |
|  | public void TestFinished(ITestResult result) { } |
|  | public void TestStarted(ITest test) { } |
|  |  |
|  | public void RunFinished(ITestResult testResults) |
|  | { |
|  | var path = Path.Combine(Application.persistentDataPath, "testresults.xml"); |
|  | using (var xmlWriter = XmlWriter.Create(path, new XmlWriterSettings { Indent = true })) |
|  | testResults.ToXml(true).WriteTo(xmlWriter); |
|  |  |
|  | System.Console.WriteLine($"\\n Test results written to: {path}\\n"); |
|  | Application.Quit(testResults.FailCount > 0 ? 1 : 0); |
|  | } |
|  | } |

[view raw](https://gist.github.com/webcontent112233/4be22a98e2c1e7024768dec91ee8439e/raw/1e9fae645fc0b4a03456d0eb1e362e3ae08d548a/ResultSerializer) [ResultSerializer](https://gist.github.com/webcontent112233/4be22a98e2c1e7024768dec91ee8439e#file-resultserializer)
hosted with ❤ by [GitHub](https://github.com/)

![Code](https://unity.com/_next/image?url=https%3A%2F%2Fcdn.sanity.io%2Fimages%2Ffuvbjjlp%2Fproduction%2F836cf46ab597d85c8b8a694639d09c4c313df5be-810x392.jpg&w=3840&q=75)

The result outputs can be found in the testresults.xml file located on your platform’s Application.persistentDataPath location

### Running a test after splitting build and run

With **SetupPlaymodeTestPlayer.cs** and **ResultSerializer.cs** combined, the build and run processes are now split. Running tests will output the results to **testresults.xml** located on the player platform’s Application.persistentDataPath [location](https://web.archive.org/web/20240415020832/https://docs.unity3d.com/ScriptReference/Application-persistentDataPath.html).

To use some of the types in these hook classes, you’ll need to add an extra reference to **Tests.asmdef**. Update it to add the UnityEditor.UI.EditorTests assembly definition reference.

Running the Tests in the Player will now yield a player build output under your project in the **TestPlayers** folder and a testresults.xml file in the Application.persistentDataPath location.

![Ebook cover art](https://unity.com/_next/image?url=https%3A%2F%2Fcdn.sanity.io%2Fimages%2Ffuvbjjlp%2Fproduction%2Ffb83ff7f249af6b7a7fe164741566c7472ae85e4-810x453.jpg&w=3840&q=75)

### More resources on testing in Unity

**Unity Test Framework course**

The Test Framework package includes [a testing course](https://web.archive.org/web/20240415020832/https://docs.unity3d.com/Packages/com.unity.test-framework@1.3/manual/course/welcome.html) featuring sample exercises to help you learn more about testing with Unity. Be sure to grab the project files for the course using the Package Manager.

Using **Package Manager** **>** **Packages: Unity Registry** **>** **Test Framework**, locate the Samples drop-down list and import the course exercises.

The exercises will be imported into your project and located under **Assets/Samples/Test Framework**. Each sample includes an exercise folder for you to work under, as well as a solution to compare your own work against as you follow along.

**QA your code with UTF**

This [Unite Copenhagen talk](https://web.archive.org/web/20240415020832/https://www.youtube.com/watch?v=wTiF2D0_vKA) about UTF goes into more detail and offers some other interesting use cases for test customization. Be sure to check it out to see what else is possible.

**Debugging in Unity**

Speed up your debugging workflow in Unity with articles on:

[\- Microsoft Visual Studio 2022](https://web.archive.org/web/20240415020832/https://unity.com/how-to/debugging-with-microsoft-visual-studio-2022)

[\- Microsoft Visual Studio Code](https://web.archive.org/web/20240415020832/https://unity.com/how-to/debugging-with-microsoft-visual-studio-code)

**Advanced technical e-books**

Unity provides a number of advanced guides to help professional developers optimize game code. [_Create a C# style guide: Write cleaner code that scales_](https://web.archive.org/web/20240415020832/https://resources.unity.com/games/create-code-style-guide-e-book?ungated=true) compiles advice from industry experts on how to create a code style guide to help your team develop a clean, readable, and scalable codebase.

Another popular guide with our users is [_70+ tips to increase productivity with Unity_](https://web.archive.org/web/20240415020832/https://resources.unity.com/games/ebook-improve-workflow?ungated=true). It’s packed with time-saving tips to improve your day-to-day aggregate workflow with Unity 2020 LTS, including tips even experienced developers might have missed out on.

**Documentation**

Explore the latest TestRunner API further, learn about other UTF Custom attributes, and discover further lifecycles to hook into with the UTF [documentation](https://web.archive.org/web/20240415020832/https://docs.unity3d.com/Packages/com.unity.test-framework@1.3/manual/course/welcome.html).

Find all of Unity’s advanced e-books and articles in the [Unity best practices hub](https://web.archive.org/web/20240415020832/https://unity.com/how-to).

![Unity Logo](https://cdn.cookielaw.org/logos/0be70f5e-5e8c-4b5b-a70e-3c3899308c62/bd2f7f6c-aedd-4cb5-9a23-928ed573901d/8506c1ab-21ee-4752-8318-a825f65bde2f/unity-logo.png)

## Privacy Preference Center

Opt-Out Request Honored

## Privacy Preference Center

- ### Your Privacy

- ### Functional Cookies

- ### Performance Cookies

- ### Targeting Cookies

- ### Strictly Necessary Cookies


#### Your Privacy

When you visit any website, it may store or retrieve information on your browser, mostly in the form of cookies. This information might be about you, your preferences, or your device, and is mostly used to make the site work as you expect. The information does not usually identify you directly, but it can give you a more personalized web experience. Because we respect your right to privacy, you can choose not to allow some types of cookies. Click on the different category headings to learn more and change our default settings. Blocking some types of cookies may impact your experience of the site and the services we are able to offer.


[More information](https://unity.com/legal/cookie-policy)

#### Functional Cookies

Functional CookiesInactive

These cookies enable the website to provide enhanced functionality and personalisation. They may be set by us or by third party providers whose services we have added to our pages. If you do not allow these cookies then some or all of these services may not function properly.

Cookies Details

#### Performance Cookies

Performance CookiesInactive

These cookies allow us to count visits and traffic sources so we can measure and improve the performance of our site. They help us to know which pages are the most and least popular and see how visitors move around the site. All information these cookies collect is aggregated and therefore anonymous. If you do not allow these cookies we will not know when you have visited our site, and will not be able to monitor its performance.

Cookies Details

#### Targeting Cookies

Targeting CookiesInactive

These cookies may be set through our site by our advertising partners. They may be used by those companies to build a profile of your interests and show you relevant adverts on other sites. They do not store directly personal information, but are based on uniquely identifying your browser and internet device. If you do not allow these cookies, you will experience less targeted advertising. Some 3rd party video providers do not allow video views without targeting cookies. If you are experiencing difficulty viewing a video, you will need to set your cookie preferences for targeting to yes if you wish to view videos from these providers. Unity does not control this.

Cookies Details

#### Strictly Necessary Cookies

Always Active

These cookies are necessary for the website to function and cannot be switched off in our systems. They are usually only set in response to actions made by you which amount to a request for services, such as setting your privacy preferences, logging in or filling in forms. You can set your browser to block or alert you about these cookies, but some parts of the site will not then work. These cookies do not store any personally identifiable information.

Cookies Details

Back Button

### Cookie List

Filter Button

ConsentLeg.Interest

checkbox labellabel

checkbox labellabel

checkbox labellabel

Clear

- checkbox labellabel


ApplyCancel

Confirm my choices

Reject allAllow all

[![Powered by Onetrust](https://cdn.cookielaw.org/logos/static/powered_by_logo.svg)](https://www.onetrust.com/solutions/consent-and-preferences/?utm_source=cmp&utm_medium=cmpbanner)

Your Privacy \[\`dialog closed\`\]